from datetime import datetime

import yfinance as yf
from flask import Flask, request
from flask_cors import CORS

import model.output.mkt_data_pb2 as MarketData

app = Flask(__name__)
CORS(app)

start_date = '2016-10-18'
end_date = '2023-10-10'


def download_financial_data(symbol, start=start_date, end=end_date, canadian=True):
    symbol = f"{symbol}.TO" if canadian else symbol
    data = yf.download(symbol, start=start, end=end)
    return data[["Adj Close"]]


def convert_to_date(dt: datetime):
    return dt.strftime("%Y-%m-%d")


def generate_proto_Ticker(symbol: str, name: str = "", sector: str = ""):
    ticker = MarketData.Ticker()
    ticker.symbol = symbol
    ticker.name = name
    ticker.sector = sector
    return ticker


def generate_proto_Value(date: str, price: float):
    value = MarketData.Value()
    value.date = date
    value.price = price
    return value


@app.route('/mkt/ticker/name/<symbol>', methods=['GET'])
def get_ticker_name(symbol):
    # http://localhost:8083/mkt/ticker/name/CCO
    ticker = yf.Ticker(symbol + ".TO")
    return ticker.info['longName']


@app.route('/proto/mkt/ticker/name/<symbol>', methods=['GET'])
def get_ticker_name_proto(symbol):
    # http://localhost:8083/proto/mkt/ticker/name/CCO
    ticker = yf.Ticker(symbol + ".TO")
    ticker_proto = generate_proto_Ticker(symbol=symbol, name=ticker.info['longName'])
    print(ticker_proto)

    return ticker_proto.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/mkt/ticker/sector/<symbol>', methods=['GET'])
def get_ticker_sector(symbol):
    # http://localhost:8083/mkt/ticker/sector/CCO
    return yf.Ticker(symbol + ".TO").info['sector']


@app.route('/proto/mkt/ticker/sector/<symbol>', methods=['GET'])
def get_ticker_sector_proto(symbol):
    # http://localhost:8083/proto/mkt/ticker/sector/CCO
    ticker = yf.Ticker(symbol + ".TO")
    ticker_proto = generate_proto_Ticker(symbol=symbol, sector=ticker.info['sector'])
    print(ticker_proto)

    return ticker_proto.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


@app.route('/mkt', methods=['GET'])
def get_mkt_data():
    # http://localhost:8083/mkt?symbol=CM&start=2023-10-01&end=2023-10-09
    symbol = request.args.get('symbol')
    start = request.args.get('start')
    end = request.args.get('end')

    data = download_financial_data(symbol, start, end)
    values = [{"date": convert_to_date(index), "price": row['Adj Close']} for index, row in data.iterrows()]
    return {
        "symbol": symbol,
        "name": get_ticker_name(symbol),
        "sector": get_ticker_sector(symbol),
        "data": values
    }


@app.route('/proto/mkt', methods=['GET'])
def get_mkt_data_proto():
    # http://localhost:8083/proto/mkt?symbol=CM&start=2023-10-01&end=2023-10-09
    symbol = request.args.get('symbol')
    start = request.args.get('start')
    end = request.args.get('end')

    data = download_financial_data(symbol, start, end)
    ticker = generate_proto_Ticker(symbol, name=get_ticker_name(symbol), sector=get_ticker_sector(symbol))
    for index, row in data.iterrows(): ticker.data.append(generate_proto_Value(convert_to_date(index), row['Adj Close']))
    print(ticker)

    return ticker.SerializeToString(), 200, {'Content-Type': 'application/x-protobuf'}


if __name__ == '__main__':
    app.run(port=8083, debug=True)
