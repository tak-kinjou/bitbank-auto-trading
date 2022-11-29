import requests
import time
import hmac
import hashlib
import json

class Bitbank(object):
	def __init__(self, access_key, secret_key):
		self.__access_key = access_key
		self.__secret_key = secret_key
		self.__rest_api = 'https://api.bitbank.cc/v1'
		self.__public_api = 'https://public.bitbank.cc'

	def _signature(self, nonce, message):
		signature = hmac.new(self.__secret_key.encode(),
														message.encode(),
														hashlib.sha256).hexdigest()

		headers = {
			"ACCESS-KEY": self.__access_key,
			"ACCESS-NONCE": nonce,
			"ACCESS-SIGNATURE": signature,
			"Content-Type": 'application/json'
		}

		return headers

	def _request_rest_api(self, endpoint, params=None, method='GET'):
		time.sleep(1)

		nonce = str(int(time.time()))
		body = json.dumps(params) if params else ''

		try:
			if method == 'GET':
				headers = self._signature(nonce, nonce + '/v1' + endpoint + body)
				r = requests.get(self.__rest_api + endpoint, headers=headers, params=params)
			else:
				headers = self._signature(nonce, nonce + body)
				r = requests.post(self.__rest_api + endpoint, headers=headers, data=body)

		except Exception as e:
			print(e)
			raise

		return r.json()

	def _request_public_api(self, endpoint):
		time.sleep(1)

		url = self.__public_api + endpoint
		r = requests.get(url)
		return r.json()

	# Tickerの取得
	def ticker(self, pair):
		endpoint = '/' + pair + '/ticker'
		return self._request_public_api(endpoint=endpoint)

	# 口座情報の取得
	def balance(self):
		endpoint = '/user/assets'
		return self._request_rest_api(endpoint=endpoint)

	# 最新価格の取得
	def last(self, pair):
		return float(self.ticker(pair)['data']['last'])

	# 自分の持ってるポジション情報の取得
	@property
	def position(self):
		balance = self.balance()['data']['assets']

		dict = {}
		for index, item in enumerate(balance, 0):
			k = balance[index]['asset']
			v = float(balance[index]['onhand_amount'])
			if v > 0:
				dict[k] = v
		return dict

	# 取引履歴
	def trade_history(self):
		endpoint = '/user/spot/trade_history'
		return self._request_rest_api(endpoint=endpoint)

	# 最後に購入したレート
	def check_ex_rate(self, pair):
		history = self.trade_history()['data']['trades']
		transaction = [d for d in history if d['side'] == 'buy']
		for index, item in enumerate(transaction, 0):
			if transaction[index]['pair'] == pair:
				return float(transaction[index]['price'])

	# 取引所の売り板からレート取得
	def book_rate(self, pair):
		endpoint = '/' + pair + '/depth'
		book = self._request_public_api(endpoint=endpoint)

		return book['data']['asks'][0][0]

	# 取引所ステータスから最小発注単位を得る（負荷に応じて変わるため）
	def get_min_amount(self, pair):
		endpoint = '/spot/status'
		status = self._request_rest_api(endpoint=endpoint)

		for index, item in enumerate(status['data']['statuses'], 0):
			if status['data']['statuses'][index]['pair'] == pair:
				return status['data']['statuses'][index]['min_amount']

	# 新規オーダー
	def order(self, params):
		endpoint = '/user/spot/order'
		return self._request_rest_api(endpoint=endpoint, params=params, method='POST')