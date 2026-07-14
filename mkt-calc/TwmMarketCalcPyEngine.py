import argparse
import json
import os
import sys
from dataclasses import dataclass, asdict

import cvxpy as cp
import numpy
import numpy as np
import py_eureka_client.eureka_client as eureka_client
import py_eureka_client.netint_utils as netint_utils
from flask import Flask, request, jsonify
from flask_cors import CORS

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.output import mkt_data_pb2 as MarketData

app = Flask(__name__)
CORS(app)

parser = argparse.ArgumentParser()
parser.add_argument('--port', type=int, help='Port number to use', default=8101, required=False)
parser.add_argument('--useEureka', type=bool, help='Use Eureka discovery?', default=False, required=False)
args = parser.parse_args()


@dataclass
class PortfolioOptimizerParams:
    total_capital_at_start: float
    names: list[str]
    sectors: list[str]
    betas: np.ndarray
    yields: np.ndarray
    returns: np.ndarray
    std_devs: np.ndarray
    pe_ratios: np.ndarray
    max_weights_vec: np.ndarray
    corr_matrix: np.ndarray
    current_holdings_dict: dict[str, float]
    sector_caps: dict[str, float]
    max_vol: float
    max_pe: float
    risk_mode: str
    target_beta: float
    vix_level: float
    max_weight: float = 0.35
    min_yield: float = 0.03
    new_cash: float = 0.0
    objective_mode: str = "MAX_RETURN"


def _parse_correlation_matrix(correlation_matrix: MarketData.CorrelationMatrix, symbols: list[str]) -> np.ndarray:
    n = len(symbols)
    corr_array = np.eye(n)
    symbol_to_idx = {symbol: i for i, symbol in enumerate(symbols)}

    for cell in correlation_matrix.entries:
        if cell.imntRow in symbol_to_idx and cell.imntCol in symbol_to_idx:
            i = symbol_to_idx[cell.imntRow]
            j = symbol_to_idx[cell.imntCol]

            corr_array[i, j] = cell.value
            corr_array[j, i] = cell.value

    return corr_array


def _parse_str(data_map, key) -> str | Exception:
    if key in data_map: return data_map[key]
    raise Exception(f"Did not find {key} in data map")


def _parse_float(data_map, key) -> float | Exception:
    return float(_parse_str(data_map, key))


def _parse_sector_caps(data_map, key) -> dict[str, float]:
    data = _parse_str(data_map, key).strip()
    sc = {}
    for entry in data.split("|"):
        parts = entry.strip().split("=")
        sector, cap = parts[0], float(parts[1])
        sc[sector] = cap
    return sc


def _parse_portfolio(portfolio: MarketData.Portfolio):
    if not portfolio or len(portfolio.instruments) <= 1:
        print("Cannot parse portfolio")
        return None

    imnts = portfolio.instruments
    # first imnt in portfolio will have the max vals and other constants
    supply_data = imnts[0]
    data_map = supply_data.metaData

    risk_mode = _parse_str(data_map, 'risk_mode')
    objective_mode = _parse_str(data_map, 'objective_mode')
    vix = _parse_float(data_map, 'vix')
    target_beta = _parse_float(data_map, 'target_beta')
    max_vol = _parse_float(data_map, 'max_vol')
    max_pe = _parse_float(data_map, 'max_pe')
    max_weight = _parse_float(data_map, 'max_weight')
    min_yield = _parse_float(data_map, 'min_yield')
    new_cash = _parse_float(data_map, 'new_cash')
    sector_caps = _parse_sector_caps(data_map, 'sector_caps')

    symbols, sectors, betas, yields, returns, std_devs, pe_ratios, max_weight_vec = [], [], [], [], [], [], [], []
    total_capital = 0.0
    current_holdings_dict = {}

    for i in range(1, len(imnts)):
        imnt = imnts[i]
        symbol = imnt.ticker.symbol
        sector = imnt.ticker.sector
        beta = imnt.beta
        div_yield = imnt.dividendYield

        data_map = imnt.metaData
        imnt_return = _parse_float(data_map, 'return')
        std_dev = _parse_float(data_map, 'std_dev')
        pe_ratio = _parse_float(data_map, 'pe_ratio')
        imnt_max_weight = _parse_float(data_map, 'max_weight')

        capital = imnt.ticker.data[0].price
        total_capital += capital
        current_holdings_dict[symbol] = capital

        symbols.append(symbol)
        sectors.append(sector)
        betas.append(beta)
        yields.append(div_yield)
        returns.append(imnt_return)
        std_devs.append(std_dev)
        pe_ratios.append(pe_ratio)
        max_weight_vec.append(imnt_max_weight)

    corr_matrix = _parse_correlation_matrix(portfolio.correlationMatrix, symbols)
    print(f"symbols len > {len(symbols)}")
    print(f"sectors len > {len(sectors)}")
    print(f"beta len > {len(betas)}")
    print(f"yields len > {len(yields)}")
    print(f"returns len > {len(returns)}")
    print(f"std_devs len > {len(std_devs)}")
    print(f"pe_ratios len > {len(pe_ratios)}")
    print(f"max_weight_vec len > {len(max_weight_vec)}")
    print(f"corr_matrix len > {len(corr_matrix)}")

    return PortfolioOptimizerParams(
        total_capital_at_start=total_capital,
        names=symbols,  # careful here
        sectors=sectors,
        betas=np.array(betas),
        yields=np.array(yields),
        returns=np.array(returns),
        std_devs=np.array(std_devs),
        pe_ratios=np.array(pe_ratios),
        max_weights_vec=np.array(max_weight_vec),
        corr_matrix=corr_matrix,
        current_holdings_dict=current_holdings_dict,
        sector_caps=sector_caps,
        max_vol=max_vol,
        max_pe=max_pe,
        risk_mode=risk_mode,
        target_beta=target_beta,
        vix_level=vix,
        max_weight=max_weight,
        min_yield=min_yield,
        new_cash=new_cash,
        objective_mode=objective_mode
    )


def _parse_optimizer_json_to_portfolio(input_data: str) -> MarketData.Portfolio:
    data = json.loads(input_data)

    portfolio = MarketData.Portfolio()
    supply_data = MarketData.Instrument()
    supply_data.metaData['status'] = data['status']

    if data['status'] == 'optimal':
        supply_data.metaData['epr'] = str(data['summary_metrics']['expected_return'])
        supply_data.metaData['vol'] = str(data['summary_metrics']['volatility'])
        supply_data.metaData['beta'] = str(data['summary_metrics']['beta'])
        supply_data.metaData['pe'] = str(data['summary_metrics']['pe_ratio'])
        supply_data.metaData['epy'] = str(data['summary_metrics']['dividend_yield'])

        for asset in data['assets']:
            imnt = MarketData.Instrument()
            imnt.ticker.symbol = asset['ticker']
            imnt.qty = asset['weight']
            imnt.metaData['current_val'] = str(asset['current_value'])
            imnt.metaData['target_val'] = str(asset['target_value'])
            imnt.metaData['action'] = asset['action']
            portfolio.instruments.append(imnt)
    else:
        supply_data.metaData['cvxpy_status'] = data['cvxpy_status']
    portfolio.instruments.insert(0, supply_data)
    return portfolio


def run_portfolio_optimizer(total_capital_at_start: float,
                            names: list[str],
                            sectors: list[str],
                            betas: np.ndarray[tuple[float]],
                            yields: np.ndarray[tuple[float]],
                            returns: np.ndarray[tuple[float]],
                            std_devs: np.ndarray[tuple[float]],
                            pe_ratios: np.ndarray[tuple[float]],
                            max_weights_vec: np.ndarray[tuple[float]],
                            corr_matrix: numpy.ndarray,
                            current_holdings_dict: dict[str, float],
                            sector_caps: dict[str, float],
                            max_vol: float,
                            max_pe: float,
                            risk_mode: str,
                            target_beta: float,
                            vix_level: float,
                            max_weight=.35,
                            min_yield=.03,
                            new_cash=0.0,
                            objective_mode="MAX_RETURN"):
    total_to_allocate = total_capital_at_start + new_cash
    print(names)
    """
    D = np.diag(std_devs)
    covariance_matrix = D @ corr_matrix @ D
    # covariance_matrix = D @ corr_matrix @ D + 1e-7 * np.eye(len(names))

    # NEW ROBUST FIX: Eigenvalue Reconstruction
    # This forces the matrix to be mathematically "solvable"
    vals, vecs = np.linalg.eigh(covariance_matrix)
    vals = np.maximum(vals, 1e-8)  # Clip any negative or near-zero eigenvalues
    covariance_matrix = vecs @ np.diag(vals) @ vecs.T

    # Add a slightly larger diagonal "nudge" for 50+ assets
    covariance_matrix += np.eye(len(names)) * 1e-6
    """
    # --- DATA SANITIZER BLOCK ---
    # 1. Ensure everything is a clean NumPy array
    returns = np.nan_to_num(np.array(returns), nan=0.0)
    yields = np.nan_to_num(np.array(yields), nan=0.0)
    pe_ratios = np.nan_to_num(np.array(pe_ratios), nan=20.0)  # Default PE if NaN
    betas = np.nan_to_num(np.array(betas), nan=1.0)  # Default Beta if NaN

    # 2. Fix the Correlation Matrix (The most likely culprit)
    corr_matrix = np.array(corr_matrix)
    corr_matrix = np.nan_to_num(corr_matrix, nan=0.0)  # Replace NaNs with 0 (no correlation)

    # 3. Force Perfect Symmetry
    # This ensures corr[i][j] == corr[j][i] exactly
    corr_matrix = (corr_matrix + corr_matrix.T) / 2
    np.fill_diagonal(corr_matrix, 1.0)  # Ensure diagonal is exactly 1.0

    # 4. Re-calculate Covariance with a safety margin
    D = np.diag(std_devs)
    covariance_matrix = D @ corr_matrix @ D
    covariance_matrix += np.eye(len(names)) * 1e-4  # Stronger nudge for stability

    print(f"Any NaNs in returns: {np.isnan(returns).any()}")
    print(f"Any NaNs in cov: {np.isnan(covariance_matrix).any()}")
    print(f"Min std_dev: {np.min(std_devs)}")

    # OPTIMIZATION
    weights = cp.Variable(len(names))
    portfolio_variance = cp.quad_form(weights, covariance_matrix)

    # Objective logic
    if objective_mode == "MAX_YIELD":
        obj_expr = weights @ yields
    elif objective_mode == "BALANCED":
        obj_expr = 0.5 * (weights @ returns) + 0.5 * (weights @ yields)
    else:
        obj_expr = weights @ returns

    # Add small HHI penalty to favor diversification if yields are equal
    objective = cp.Maximize(obj_expr - 1e-4 * cp.sum_squares(weights))

    constraints = [
        cp.sum(weights) == 1,
        weights >= 0,
        # weights <= max_weight,  # Position Cap
        weights <= max_weights_vec,
        weights @ betas <= target_beta,
        weights @ yields >= min_yield,  # Yield Target
        weights @ pe_ratios <= max_pe,
        portfolio_variance <= max_vol ** 2
    ]

    # SECTOR CONSTRAINTS: find indices of stocks belonging to each sector and sum their weights
    unique_sectors = set(sectors)
    for sector in unique_sectors:
        if sector in sector_caps:
            # Create a boolean mask for this sector
            indices = [i for i, s in enumerate(sectors) if s == sector]
            constraints.append(cp.sum(weights[indices]) <= sector_caps[sector])

    prob = cp.Problem(objective, constraints)
    prob.solve()
    # prob.solve(verbose=True)
    # prob.solve(solver=cp.SCS, verbose=True, max_iters=5000)
    # prob.solve(solver=cp.OSQP, eps_abs=1e-5, eps_rel=1e-5, verbose=True)
    # prob.solve(solver=cp.ECOS, verbose=True)

    if prob.status == 'optimal':
        opt_w = weights.value
        portfolio_vol = float(np.sqrt(portfolio_variance.value))
        portfolio_beta = float(np.sum(opt_w * betas))
        portfolio_return = float(np.sum(opt_w * returns))
        portfolio_pe = float(np.sum(opt_w * pe_ratios))
        portfolio_yield = float(np.sum(opt_w * yields))

        asset_details = []

        print(f"============================================================")
        print(f" MARKET CONTEXT: {risk_mode}")
        print(f" VIX Level: {vix_level} | Status: {prob.status.upper()}")
        print(f"============================================================")
        print(
            f"{'Stock':<15} | {'Weight':<8} | {'Current $':<10} | {'Target $':<10} | {'Return':<9} | {'Yield':<9} | {'Action'}")
        print(f"-" * 95)

        for i, name in enumerate(names):
            opt_val = float(opt_w[i] * total_to_allocate)
            curr_val = float(current_holdings_dict.get(name, 0))
            trade_amount = opt_val - curr_val

            # Action string for print
            if trade_amount > 10:
                action_str = f"BUY ${trade_amount:,.0f}"
            elif trade_amount < -10:
                action_str = f"SELL ${abs(trade_amount):,.0f}"
            else:
                action_str = "--"

            print(
                f"{name:<15} | {opt_w[i]:<8.1%} | ${curr_val:>9,.0f} | ${opt_val:>9,.0f} | {returns[i]:>9.2%} | {yields[i]:>9.2%} | {action_str}")

            asset_details.append({
                "ticker": name,
                "weight": round(float(opt_w[i]), 4),
                "current_value": curr_val,
                "target_value": round(opt_val, 2),
                "trade_amount": round(trade_amount, 2),
                "action": action_str
            })

        print(f"============================================================")
        print(f" PORTFOLIO RISK & RETURN METRICS")
        print(f"------------------------------------------------------------")
        print(f" EXPECTED ANNUAL RETURN : {portfolio_return:>8.2%}")
        print(f" PORTFOLIO VOLATILITY   : {portfolio_vol:>8.2%} (Limit: {max_vol:.0%})")
        print(f" OVERALL PORTFOLIO BETA : {portfolio_beta:>8.2f} (Limit: {target_beta:.2f})")
        print(f" AVERAGE P/E RATIO      : {portfolio_pe:>8.1f} (Limit: {max_pe:.1f})")
        print(f" PORTFOLIO YIELD        : {portfolio_yield:>8.2%} (Min: {min_yield:.0%})")
        print(f"--- Sector Allocation ---")
        for sector in unique_sectors:
            s_weight = sum(opt_w[i] for i, s in enumerate(sectors) if s == sector)
            print(f"{sector:<15}: {s_weight:>7.1%}")

        print(f"============================================================")

        # Build final JSON response
        response_data = {
            "status": prob.status,
            "summary_metrics": {
                "expected_return": round(portfolio_return, 4),
                "volatility": round(portfolio_vol, 4),
                "beta": round(portfolio_beta, 3),
                "pe_ratio": round(portfolio_pe, 2),
                "dividend_yield": round(portfolio_yield, 4)
            },
            "assets": asset_details
        }

        return json.dumps(response_data)

    else:
        print(f"Optimization failed. Constraints are too restrictive for these assets => {prob.status}")
        error_resp = {"status": "failed", "cvxpy_status": prob.status}
        return json.dumps(error_resp)


@app.route('/calc/portfolio/optimizer', methods=['POST'])
def portfolio_optimizer():
    data = request.get_data()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    portfolio = MarketData.Portfolio()
    try:
        portfolio.ParseFromString(data)
    except Exception as e:
        return jsonify({"error": f"Failed to parse protobuf: {str(e)}"}), 400

    params = _parse_portfolio(portfolio)
    optimizer_result_json = run_portfolio_optimizer(**asdict(params))
    response_portfolio = _parse_optimizer_json_to_portfolio(optimizer_result_json)
    return response_portfolio.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/test', methods=['GET'])
def test():
    current_holdings_dict = {
        'Tech Growth': 20000,
        'Blue Chip': 20000,
        'Utility Co': 20000,
        'Consumer Staple': 20000,
        'Bank Stock': 20000
    }
    vix_level = 28.0
    max_weight = .35
    min_yield = .03

    # --- 1. DATA & MARKET SETTINGS ---
    total_capital = sum(current_holdings_dict.values())
    names = ['Tech Growth', 'Blue Chip', 'Utility Co', 'Consumer Staple', 'Bank Stock']
    sectors = ['tech', 'unknown', 'util', 'cons-cy', 'fin']

    # Fundamental & Risk Data
    betas = np.array([1.50, 1.10, 0.55, 0.45, 0.90])
    yields = np.array([0.005, 0.025, 0.045, 0.035, 0.050])
    returns = np.array([0.18, 0.11, 0.06, 0.07, 0.09])
    std_devs = np.array([0.28, 0.18, 0.12, 0.10, 0.15])
    pe_ratios = np.array([45, 18, 14, 21, 10])
    max_weight_vec = np.array([.25, .25, .25, .25, .45])
    sector_caps = {
        'fin': .40
    }

    # Contrarian Logic: Adjusting Targets based on VIX
    if vix_level > 25:
        risk_mode = "OPPORTUNISTIC (BUYING THE DIP)"
        target_beta = 1.15
        max_volatility = 0.18
        max_pe = 18.0
    else:
        risk_mode = "CONSERVATIVE (HARVESTING PnL)"
        target_beta = 0.90
        max_volatility = 0.10
        max_pe = 22.0

    # --- 2. COVARIANCE MATRIX CONSTRUCTION ---
    corr_matrix = np.array([
        [1.0, 0.7, 0.1, 0.2, 0.4],
        [0.7, 1.0, 0.2, 0.3, 0.5],
        [0.1, 0.2, 1.0, 0.6, 0.1],
        [0.2, 0.3, 0.6, 1.0, 0.2],
        [0.4, 0.5, 0.1, 0.2, 1.0]
    ])

    # Run it for a high-fear environment
    return run_portfolio_optimizer(
        total_capital_at_start=total_capital,
        names=names,
        sectors=sectors,
        betas=betas,
        yields=yields,
        returns=returns,
        std_devs=std_devs,
        pe_ratios=pe_ratios,
        max_weights_vec=max_weight_vec,
        corr_matrix=corr_matrix,
        max_vol=max_volatility,
        max_pe=max_pe,
        risk_mode=risk_mode,
        target_beta=target_beta,
        vix_level=vix_level,
        current_holdings_dict=current_holdings_dict,
        sector_caps=sector_caps,
        max_weight=max_weight,
        min_yield=min_yield,
        new_cash=0.0
    )


if __name__ == '__main__':
    print(f"Using port: {args.port}")

    if args.useEureka:
        # Initialize the Eureka client
        try:
            print("Attempting registering onto eureka server")
            local_ip = netint_utils.get_first_non_loopback_ip()  # prevent dhcp ip hostname clash

            eureka_client.init(
                eureka_server="http://localhost:2012/eureka",
                app_name="twm-calc-py-engine",
                instance_port=args.port,
                instance_ip=local_ip,
                instance_host=local_ip
            )
            print("Registered onto eureka server")
        except Exception as e:
            print("Failed to register onto eureka server ", e)

    app.run(host='0.0.0.0', port=args.port, debug=True)
