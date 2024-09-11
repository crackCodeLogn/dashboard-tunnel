rm output/mkt*py
protoc -I=. --python_out=./output mkt-data.proto
