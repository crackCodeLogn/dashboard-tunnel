import os
import sys
from datetime import datetime

import pandas as pd
import yfinance as yf
from flask import Flask, request
from flask_cors import CORS

from Instrument import Instrument

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from model.output import mkt_data_pb2 as MarketData

# import model.output.mkt_data_pb2 as MarketData

app = Flask(__name__)
CORS(app)

start_date = '2016-10-18'
end_date = '2023-10-10'

ticker_name_map = {}
country_code_map = {
    "CA": "TO",
    "US": "",
    "IN": "NS",  # Nifty-50
}

stk_exchange_map = {
    'ALV': 'V'  # tsx-v
}

direction_map = {
    'b': 'BUY',
    's': 'SELL'
}


def get_symbol(symbol, country_code="CA"):
    return f"{symbol}.{stk_exchange_map.get(symbol, country_code_map.get(country_code, ""))}"


def download_financial_data(symbol, start=start_date, end=end_date, country_code="CA", use_original_symbol=True):
    if not use_original_symbol: symbol = get_symbol(symbol, country_code)
    print(symbol)
    data = yf.download(symbol, start=start, end=end)
    return data[["Adj Close"]], symbol


def convert_to_date(dt: datetime):
    return dt.strftime("%Y-%m-%d")


def generate_proto_Ticker(symbol: str, name: str = "", sector: str = "", type: str = ""):
    ticker = MarketData.Ticker()
    ticker.symbol = symbol
    ticker.name = name
    ticker.sector = sector
    ticker.type = MarketData.InstrumentType.Value(type)
    return ticker


def generate_proto_Value(date: str, price: float):
    value = MarketData.Value()
    date_object = datetime.strptime(date, '%Y-%m-%d')
    value.date = int(date_object.strftime('%Y%m%d'))
    value.price = price
    return value


def generate_proto_Portfolio():
    return MarketData.Portfolio()


def generate_proto_Instrument(portfolio, imnt: Instrument, direction: str):
    global ticker_name_map
    imnt_proto = MarketData.Instrument()
    imnt_proto.ticker.symbol = imnt.symbol

    if imnt_proto.ticker.symbol not in ticker_name_map:
        ticker_name_map[imnt_proto.ticker.symbol] = get_ticker_name_without_country(imnt_proto.ticker.symbol)
    ticker_name = ticker_name_map[imnt_proto.ticker.symbol]

    imnt_proto.ticker.name = ticker_name
    imnt_proto.ticker.sector = imnt.sector
    imnt_proto.ticker.type = MarketData.InstrumentType.Value(imnt.type)
    value_data = generate_proto_Value(imnt.dt, imnt.ticker_price)
    imnt_proto.ticker.data.append(value_data)
    imnt_proto.qty = imnt.qty
    imnt_proto.accountType = MarketData.AccountType.Value(imnt.account)
    imnt_proto.direction = MarketData.Direction.Value(direction)
    portfolio.instruments.append(imnt_proto)


@app.route('/ping', methods=['GET'])
def ping():
    import time
    timestamp = (int)(time.time() * 1000)
    print(f"PINGING back with status {timestamp}")
    return f"ALIVE-{timestamp}"


@app.route('/mkt/<country_code>/ticker/type/<symbol>', methods=['GET'])
def get_ticker_type(country_code, symbol):
    # http://localhost:8083/mkt/CA/ticker/type/CCO
    ticker = yf.Ticker(get_symbol(symbol, country_code))
    return ticker.info['quoteType']


@app.route('/mkt/ticker/type/<symbol>', methods=['GET'])
def get_ticker_type_without_country(symbol):
    # http://localhost:8083/mkt/ticker/type/CCO
    ticker = yf.Ticker(symbol)
    return ticker.info['quoteType']


@app.route('/mkt/<country_code>/ticker/name/<symbol>', methods=['GET'])
def get_ticker_name(country_code, symbol):
    # http://localhost:8083/mkt/CA/ticker/name/CCO
    ticker = yf.Ticker(get_symbol(symbol, country_code))
    return str(ticker.info['longName']).replace(",", "")


@app.route('/mkt/ticker/name/<symbol>', methods=['GET'])
def get_ticker_name_without_country(symbol):
    # http://localhost:8083/mkt/ticker/name/CCO
    ticker = yf.Ticker(symbol)
    return str(ticker.info['longName']).replace(",", "")


# @app.route('/proto/mkt/<country_code>/ticker/name/<symbol>', methods=['GET'])
# def get_ticker_name_proto(country_code, symbol):
#     # http://localhost:8083/proto/mkt/CA/ticker/name/CCO
#     ticker = yf.Ticker(symbol + country_code_map[country_code])
#     ticker_proto = generate_proto_Ticker(symbol=symbol, name=ticker.info['longName'])
#     print(ticker_proto)
#
#     return ticker_proto.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/mkt/<country_code>/ticker/sector/<symbol>', methods=['GET'])
def get_ticker_sector(country_code, symbol):
    # http://localhost:8083/mkt/CA/ticker/sector/CCO
    return yf.Ticker(get_symbol(symbol, country_code)).info.get('sector', 'Unknown')


@app.route('/mkt/ticker/sector/<symbol>', methods=['GET'])
def get_ticker_sector_without_country(symbol):
    # http://localhost:8083/mkt/ticker/sector/CCO
    return yf.Ticker(symbol).info.get('sector', 'Unknown')


@app.route('/mkt/<country_code>/ticker/dividend/<symbol>', methods=['GET'])
def get_ticker_dividend(country_code, symbol) -> str:
    # http://localhost:8083/mkt/CA/ticker/dividend/CCO
    return str(yf.Ticker(get_symbol(symbol, country_code)).info.get('dividendYield', '0.0'))


@app.route('/mkt/ticker/dividend/<symbol>', methods=['GET'])
def get_ticker_dividend_without_country(symbol) -> str:
    # http://localhost:8083/mkt/ticker/dividend/CCO.TO
    return str(yf.Ticker(symbol).info.get('dividendYield', '0.0'))


# @app.route('/proto/mkt/<country_code>/ticker/sector/<symbol>', methods=['GET'])
# def get_ticker_sector_proto(country_code, symbol):
#     # http://localhost:8083/proto/mkt/CA/ticker/sector/CCO
#     ticker = yf.Ticker(symbol + country_code_map[country_code])
#     ticker_proto = generate_proto_Ticker(symbol=symbol, sector=ticker.info['sector'])
#     print(ticker_proto)
#
#     return ticker_proto.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/mkt', methods=['GET'])
def get_mkt_data():
    # http://localhost:8083/mkt?symbol=CM&start=2023-10-01&end=2023-10-09&original=1
    # http://localhost:8083/mkt?symbol=CM.TO&start=2023-10-01&end=2023-10-09&original=1
    # http://localhost:8083/mkt?symbol=CM.TO&start=2023-10-01&end=2023-10-09&original=0
    symbol = request.args.get('symbol')
    start = request.args.get('start')
    end = request.args.get('end')
    country_code = request.args.get('country', '')
    use_original_symbol = int(request.args.get('original')) == 1
    if country_code == '' and not use_original_symbol:
        country_ext = symbol[symbol.rindex('.') + 1:]
        for key in country_code_map.keys():
            if country_ext == country_code_map[key]:
                country_code = key
                break
        symbol = symbol[:symbol.rindex('.')]
    data, actual_symbol = download_financial_data(symbol, start, end, country_code,
                                                  use_original_symbol=use_original_symbol)
    values = [{"date": convert_to_date(index), "price": row['Adj Close']} for index, row in data.iterrows()]
    return {
        "symbol": actual_symbol,
        "name": get_ticker_name(country_code, symbol) if not use_original_symbol else
        get_ticker_name_without_country(symbol),
        "sector": get_ticker_sector(country_code, symbol) if not use_original_symbol else
        get_ticker_sector_without_country(symbol),
        "type": get_ticker_type(country_code, symbol) if not use_original_symbol else
        get_ticker_type_without_country(symbol),
        "data": values
    }


@app.route('/proto/mkt', methods=['GET'])
def get_mkt_data_proto():
    # http://localhost:8083/proto/mkt?symbol=CM&start=2023-10-01&end=2023-10-09
    symbol = request.args.get('symbol')
    start = request.args.get('start')
    end = request.args.get('end')
    country_code = request.args.get('country', '')
    use_original_symbol = int(request.args.get('original')) == 1
    if country_code == '' and not use_original_symbol:
        country_ext = symbol[symbol.rindex('.') + 1:]
        for key in country_code_map.keys():
            if country_ext == country_code_map[key]:
                country_code = key
                break
        symbol = symbol[:symbol.rindex('.')]
    data, actual_symbol = download_financial_data(symbol, start, end, country_code,
                                                  use_original_symbol=use_original_symbol)
    ticker = generate_proto_Ticker(actual_symbol,
                                   name=get_ticker_name(country_code, symbol) if not use_original_symbol else
                                   get_ticker_name_without_country(symbol),
                                   sector=get_ticker_sector(country_code, symbol) if not use_original_symbol else
                                   get_ticker_sector_without_country(symbol),
                                   type=get_ticker_type(country_code, symbol) if not use_original_symbol else
                                   get_ticker_type_without_country(symbol))
    for index, row in data.iterrows(): ticker.data.append(
        generate_proto_Value(convert_to_date(index), row['Adj Close']))
    print(ticker)

    return ticker.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


## Only for CA
@app.route('/proto/mkt/portfolio/<direction>', methods=['GET'])
def get_mkt_portfolio_data(direction):
    """
    GET market portfolio based on the direction supplied
    :param direction:
        - b: for getting data of stocks bought
        - s: for getting data of stocks sold
    :return: proto based data Portfolio from market data protobuf
    """
    exempt_ticker_in_data_source = ["Total invested"]
    imnts = []

    import platform
    src_mkt_data = f"/var/mkt-data-{direction}.txt" if platform.system() == "Linux" else "C:\\mkt-data.txt"
    direction = direction_map[direction]

    data_source = pd.read_csv(open(src_mkt_data).readline())
    for index, row in data_source.iterrows():
        ticker = row['Stock code']
        if type(ticker) == float or ticker in exempt_ticker_in_data_source: continue
        qty = row['Qty']
        dt = str(row['Trade date'])
        ticker_price = float(row['Price per share'])
        sector = str(row['Sector'])
        account = str(row['Account'])
        symbol = get_symbol(ticker)
        imnt_type = get_ticker_type_without_country(symbol)
        imnt = Instrument(symbol, qty, dt, ticker_price, sector, account, imnt_type)
        print(imnt)
        imnts.append(imnt)

    portfolio = generate_proto_Portfolio()
    [generate_proto_Instrument(portfolio, imnt, direction) for imnt in imnts]
    print(portfolio)

    return portfolio.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


if __name__ == '__main__':
    app.run(port=8083, debug=True)
