class Instrument:
    def __init__(self, symbol, qty, dt, ticker_price, sector, account, type, **kwargs) -> None:
        self.symbol = symbol
        self.qty = qty
        self.dt = dt
        self.ticker_price = ticker_price
        self.sector = sector
        self.account = account
        self.type = type

    def __repr__(self) -> str:
        return str(self.__dict__)
