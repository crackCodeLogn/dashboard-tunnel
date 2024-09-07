rm output/*py
protoc -I=. --python_out=./output mkt-data.proto