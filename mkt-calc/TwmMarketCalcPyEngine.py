import argparse
import os
import sys
from dataclasses import dataclass, asdict

import cvxpy as cp
import numpy
import numpy as np
import py_eureka_client.eureka_client as eureka_client
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
    betas: np.ndarray
    yields: np.ndarray
    returns: np.ndarray
    std_devs: np.ndarray
    pe_ratios: np.ndarray
    corr_matrix: np.ndarray
    current_holdings_dict: dict[str, float]
    max_vol: float
    max_pe: float
    risk_mode: str
    target_beta: float
    vix_level: float
    max_weight: float = 0.35
    min_yield: float = 0.03
    new_cash: float = 0.0


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


def _parse_str(data_map, key):
    if key in data_map: return data_map[key]
    raise Exception(f"Did not find {key} in data map")


def _parse_float(data_map, key):
    return float(_parse_str(data_map, key))


def _parse_portfolio(portfolio: MarketData.Portfolio):
    if not portfolio or len(portfolio.instruments) <= 1:
        print("Cannot parse portfolio")
        return None

    imnts = portfolio.instruments
    # first imnt in portfolio will have the max vals and other constants
    supply_data = imnts[0]
    data_map = supply_data.metaData

    risk_mode = _parse_str(data_map, 'risk_mode')
    vix = _parse_float(data_map, 'vix')
    target_beta = _parse_float(data_map, 'target_beta')
    max_vol = _parse_float(data_map, 'max_vol')
    max_pe = _parse_float(data_map, 'max_pe')
    max_weight = _parse_float(data_map, 'max_weight')
    min_yield = _parse_float(data_map, 'min_yield')
    new_cash = _parse_float(data_map, 'new_cash')

    symbols, betas, yields, returns, std_devs, pe_ratios = [], [], [], [], [], []
    total_capital = 0.0
    current_holdings_dict = {}

    for i in range(1, len(imnts)):
        imnt = imnts[i]
        symbol = imnt.ticker.symbol
        beta = imnt.beta
        div_yield = imnt.dividendYield

        data_map = imnt.metaData
        imnt_return = _parse_float(data_map, 'return')
        std_dev = _parse_float(data_map, 'std_dev')
        pe_ratio = _parse_float(data_map, 'pe_ratio')

        capital = imnt.ticker.data[0].price
        total_capital += capital
        current_holdings_dict[symbol] = capital

        symbols.append(symbol)
        betas.append(beta)
        yields.append(div_yield)
        returns.append(imnt_return)
        std_devs.append(std_dev)
        pe_ratios.append(pe_ratio)

    corr_matrix = _parse_correlation_matrix(portfolio.correlationMatrix, symbols)

    return PortfolioOptimizerParams(
        total_capital_at_start=total_capital,
        names=symbols,  # careful here
        betas=np.array(betas),
        yields=np.array(yields),
        returns=np.array(returns),
        std_devs=np.array(std_devs),
        pe_ratios=np.array(pe_ratios),
        corr_matrix=corr_matrix,
        current_holdings_dict=current_holdings_dict,
        max_vol=max_vol,
        max_pe=max_pe,
        risk_mode=risk_mode,
        target_beta=target_beta,
        vix_level=vix,
        max_weight=max_weight,
        min_yield=min_yield,
        new_cash=new_cash
    )


def run_portfolio_optimizer(total_capital_at_start: float,
                            names: list[str],
                            betas: np.ndarray[tuple[float]],
                            yields: np.ndarray[tuple[float]],
                            returns: np.ndarray[tuple[float]],
                            std_devs: np.ndarray[tuple[float]],
                            pe_ratios: np.ndarray[tuple[float]],
                            corr_matrix: numpy.ndarray,
                            current_holdings_dict: dict[str, float],
                            max_vol: float,
                            max_pe: float,
                            risk_mode: str,
                            target_beta: float,
                            vix_level: float,
                            max_weight=.35, min_yield=.03,
                            new_cash=0.0,
                            objective_mode="MAX_RETURN"):
    total_to_allocate = total_capital_at_start + new_cash

    D = np.diag(std_devs)
    covariance_matrix = D @ corr_matrix @ D

    # OPTIMIZATION
    weights = cp.Variable(len(names))
    portfolio_variance = cp.quad_form(weights, covariance_matrix)

    if objective_mode == "MAX_YIELD":
        objective = cp.Maximize(weights @ yields)
    elif objective_mode == "BALANCED":
        objective = cp.Maximize(0.5 * (weights @ returns) + 0.5 * (weights @ yields))
    else:
        objective = cp.Maximize(weights @ returns)

    constraints = [
        cp.sum(weights) == 1,
        weights >= 0,
        weights <= max_weight,  # Position Cap
        weights @ betas <= target_beta,
        weights @ yields >= min_yield,  # Yield Target
        weights @ pe_ratios <= max_pe,
        portfolio_variance <= max_vol ** 2
    ]

    prob = cp.Problem(objective, constraints)
    prob.solve()

    # COMPREHENSIVE OUTPUT
    if prob.status == 'optimal':
        opt_w = weights.value
        portfolio_vol = np.sqrt(portfolio_variance.value)
        portfolio_beta = np.sum(opt_w * betas)
        portfolio_return = np.sum(opt_w * returns)
        portfolio_pe = np.sum(opt_w * pe_ratios)
        portfolio_yield = np.sum(opt_w * yields)

        print(f"============================================================")
        print(f" MARKET CONTEXT: {risk_mode}")
        print(f" VIX Level: {vix_level} | Status: {prob.status.upper()}")
        print(f"============================================================")
        print(
            f"{'Stock':<15} | {'Weight':<8} | {'Current $':<10} | {'Target $':<10} | {'Return 0':<9} | {'Yield 0':<9} | {'Action'}")
        print(f"-" * 70)

        for i, name in enumerate(names):
            # Target $ is based on the NEW total
            opt_val = opt_w[i] * total_to_allocate
            curr_val = current_holdings_dict.get(name, 0)
            diff = opt_val - curr_val

            # If diff is positive, we use 'new_cash' or proceeds from 'sells' to buy
            if diff > 10:
                action = f"BUY ${diff:,.0f}"
            elif diff < -10:
                action = f"SELL ${abs(diff):,.0f}"
            else:
                action = "--"

            print(
                f"{name:<15} | {opt_w[i]:<8.1%} | ${curr_val:>9,.0f} | ${opt_val:>9,.0f} | {returns[i]:>9,.2f} | {yields[i]:>9,.2f} | {action}")

        print(f"============================================================")
        print(f" PORTFOLIO RISK & RETURN METRICS")
        print(f"------------------------------------------------------------")
        print(f" EXPECTED ANNUAL RETURN : {portfolio_return:>8.2%}")
        print(f" PORTFOLIO VOLATILITY   : {portfolio_vol:>8.2%} (Limit: {max_vol:.0%})")
        print(f" OVERALL PORTFOLIO BETA : {portfolio_beta:>8.2f} (Limit: {target_beta:.2f})")
        print(f" AVERAGE P/E RATIO      : {portfolio_pe:>8.1f} (Limit: {max_pe:.1f})")
        print(f" PORTFOLIO YIELD        : {portfolio_yield:>8.2%} (Min: {min_yield:.0%})")
        print(f"============================================================")
    else:
        print(f"Optimization failed. Constraints are too restrictive for these assets => {prob.status}")

    return "Done for now"


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
    return run_portfolio_optimizer(**asdict(params))


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

    # Fundamental & Risk Data
    betas = np.array([1.50, 1.10, 0.55, 0.45, 0.90])
    yields = np.array([0.005, 0.025, 0.045, 0.035, 0.050])
    returns = np.array([0.18, 0.11, 0.06, 0.07, 0.09])
    std_devs = np.array([0.28, 0.18, 0.12, 0.10, 0.15])
    pe_ratios = np.array([45, 18, 14, 21, 10])

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
        betas=betas,
        yields=yields,
        returns=returns,
        std_devs=std_devs,
        pe_ratios=pe_ratios,
        corr_matrix=corr_matrix,
        max_vol=max_volatility,
        max_pe=max_pe,
        risk_mode=risk_mode,
        target_beta=target_beta,
        vix_level=vix_level,
        current_holdings_dict=current_holdings_dict,
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
            eureka_client.init(
                eureka_server="http://localhost:2012/eureka",
                app_name="twm-calc-py-engine",
                instance_port=args.port
            )
            print("Registered onto eureka server")
        except Exception as e:
            print("Failed to register onto eureka server ", e)

    app.run(host='0.0.0.0', port=args.port, debug=True)
