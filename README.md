# auto-trading-bot-for-bitbank

仮想通貨自動売買BOT(bitbank)

## セットアップ

### 環境変数をセット

- settings.py内のBIT_ACCESS_KEY、BIT_SECRET_KEYにbitbankのAPIキーとシークレットキーを記述。
- settings.py内のLINE_ACCESS_TOKENにLINE Notifyのトークンを記述。

### Dockerコンテナを起動v

```
$ docker-compose up -d --build
```

### Dockerコンテナの中へ入る

```
$ docker exec -it python3 /bin/bash
```

### BOTを起動

```
$ cd opt
$ python start.py
```

購入時、売却時、エラー時はLINE通知が飛んでいく。
