# ライブラリ
import time
import traceback,sys
import numpy as np
import pandas as pd
pd.options.display.float_format = '{:.2f}'.format
from datetime import datetime, timedelta
import datetime
from tqdm import tqdm
from scipy.stats import linregress
import python_bitbankcc
from bitbank import Bitbank
from line_notify_bot import LINENotifyBot

# API_TOKEN情報取得
import settings
ACCESS_KEY = settings.BIT_ACCESS_KEY
SECRET_KEY = settings.BIT_SECRET_KEY
LINE_ACCESS_TOKEN = settings.LINE_ACCESS_TOKEN

linebot = LINENotifyBot(access_token=LINE_ACCESS_TOKEN)
bitbank = Bitbank(access_key=ACCESS_KEY, secret_key=SECRET_KEY)

"""	 
#################################################################################
# ここでは直近30日分の15分BTCロウソク足をテクニカル分析して自動売買の判断をしています。
# そのまま使用すると損をしますので適宜修正してください。
#################################################################################
"""
# 取引銘柄
ticker = 'btc'	#（btc, eth, xrp, など）
pair = ticker + '_jpy'
data_acquisition_period = 30 # 取得期間（ここでは30日とする）

# ロウソク足データの期間
candle_period = 15
candle_unit = 'min'
candle_type = str(candle_period)+candle_unit

# 分析する期間
# 2880 = (60[分]/15[分足])*24[時間]*30[日] 
analysis_period = 2880 # 30日分

# 手数料
buy_cost = 0.0012 # 購入金額の0.12%
sell_cost = 0.0002 # 売却金額の0.02%

# MACD
fast_ema = 12 # 短期EMAの期間
slow_ema = 26 # 長期EMAの期間
smooth = 9 # MACDシグナルライン期間

# SMA（単純）移動平均線
sma_line = analysis_period

# トレンドライン
trade_line = analysis_period

# ストキャスティクス
fastk_period=5
slowk_period=3
slowd_period=3

# その他
continue_count = 0

# ロウソク足データを取得
def get_candles(start, end, pair, candle_type):
	pub = python_bitbankcc.public()	
	ohlcv_data = []

	start = start.strftime('%Y%m%d')
	end = end.strftime('%Y%m%d')
	start_date = datetime.datetime.strptime(start,"%Y%m%d")
	end_date = datetime.datetime.strptime(end,"%Y%m%d")
	# 日付の引き算
	span = end_date - start_date
	# 1時間ごとに時間足データを取得し、結合していく
	for counter in tqdm(range(span.days + 1)):
		the_day = start_date + datetime.timedelta(days = counter)
		try:
			value = pub.get_candlestick(pair, candle_type, the_day.strftime("%Y%m%d"))
			ohlcv = value["candlestick"][0]['ohlcv']
			# 結合
			ohlcv_data.extend(ohlcv)
		except:
			raise Exception('ロウソク足データ取得で失敗')

	col = ["Open","High","Low","Close","Volume","UnixTime"]
	df_sum = pd.DataFrame(ohlcv_data, columns = col)
	return df_sum

# MACDを取得
def get_macd(candle_close, slow, fast, smooth):
	exp1 = candle_close.ewm(span = fast, adjust = False).mean()
	exp2 = candle_close.ewm(span = slow, adjust = False).mean()
	macd = pd.DataFrame(exp1 - exp2).rename(columns = {'Close':'macd'})
	signal = pd.DataFrame(macd.ewm(span = smooth, adjust = False).mean()).rename(columns = {'macd':'signal'})
	hist = pd.DataFrame(macd['macd'] - signal['signal']).rename(columns = {0:'hist'})
	frames =  [macd, signal, hist]
	df = pd.concat(frames, join = 'inner', axis = 1)
	return df

# 高値の始点/支点を取得
def get_highpoint(candle, start, end):
	chart = candle[start:end+1]
	while len(chart)>3:
		regression = linregress(
			x = chart['time_id'],
			y = chart['High'],
		)
		chart = chart.loc[chart['High'] > regression[0] * chart['time_id'] + regression[1]]
		if (regression[0] == 0.0):
			return chart
	return chart

# 安値の始点/支点を取得
def get_lowpoint(candle, start, end):
	chart = candle[start:end+1]
	while len(chart)>3:
		regression = linregress(
			x = chart['time_id'],
			y = chart['Low'],
		)
		chart = chart.loc[chart['Low'] < regression[0] * chart['time_id'] + regression[1]]
		if (regression[0] == 0.0):
			return chart
	return chart

# 上昇トレンドライン、下降トレンドラインを取得
def get_trendlines(candle, span, min_interval=3):
	margin = len(candle) - span
	trendline_high = []
	trendline_low = []
	candle = candle.astype(np.float32)

	# 高値の下降トレンドラインを生成
	for i in candle.index[::int(span/2)]:
		if (i < margin) :
			continue
		highpoint = get_highpoint(candle, i, i + span)
		# ポイントが2箇所未満だとエラーになるので回避する
		if len(highpoint) < 2:
			continue
		# 始点と支点が近過ぎたらトレンドラインとして引かない
		if abs(highpoint.index[0] - highpoint.index[1]) < min_interval:
			continue
		regression = linregress(
			x = highpoint['time_id'],
			y = highpoint['High'],
		)
		if regression[0] < 0.0:
			trendline_high.append(regression[0] * candle['time_id'][i:i+span*2] + regression[1])

	# 安値の上昇トレンドラインを生成
	for i in candle.index[::int(span/2)]:
		if (i < margin) :
			continue
		lowpoint = get_lowpoint(candle, i, i + span)
		# ポイントが2箇所未満だとエラーになるので回避する
		if len(lowpoint) < 2:
			continue
		# 始点と支点が近過ぎたらトレンドラインとして引かない
		if abs(lowpoint.index[0] - lowpoint.index[1]) < min_interval:
			continue
		regression = linregress(
			x = lowpoint['time_id'],
			y = lowpoint['Low'],
		)
		if regression[0] > 0.0:
			trendline_low.append(regression[0] * candle['time_id'][i:i+span*2] + regression[1])

	return trendline_high,trendline_low

# ボリンジャーバンドを取得
def get_bolinger(candle_close):
	bolinger = pd.DataFrame()
	bolinger['average20'] = candle_close.rolling(window=20).mean()
	bolinger['std'] = candle_close.rolling(window=20).std()
	bolinger['+2σ'] = bolinger['average20'] + (bolinger['std'] * 2)
	bolinger['-2σ'] = bolinger['average20'] - (bolinger['std'] * 2)
	bolinger_average20 = []
	for myvalue in bolinger['average20']:
		bolinger_average20.append(round(float(myvalue),0))
	bolinger_std = []
	for myvalue in bolinger['std']:
		bolinger_std.append(round(float(myvalue),0))
	bolinger_p2sigm = []
	for myvalue in bolinger['+2σ']:
		bolinger_p2sigm.append(round(float(myvalue),0))
	bolinger_m2sigm = []
	for myvalue in bolinger['-2σ']:
		bolinger_m2sigm.append(round(float(myvalue),0))
	return bolinger_average20, bolinger_std, bolinger_p2sigm, bolinger_m2sigm

# ロウソク足データをチェック
def candles_check(candle, continue_count):
	now_candle_time = datetime.datetime.fromtimestamp(int(str(float(candle['UnixTime'].iloc[-1]))[:10])).strftime("%Y-%m-%d %H:%M:00")
	now_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:00")
	time_abs = abs(datetime.datetime.strptime(now_candle_time, '%Y-%m-%d %H:%M:%S') - datetime.datetime.strptime(now_time, '%Y-%m-%d %H:%M:%S'))
	
	if time_abs.seconds > 120 : # API直近データと現時刻の差分、2分以内は許容する
		if (continue_count > 5) : # 5回以上コンティニューしたらエラーにする
			raise Exception('ロウソク足データのチェックで失敗')
		return False
	return True

# 売買チェック
def buy_sell_judgment(is_position, prices, bolinger_std, macd, sma, trand_high, trand_low): 
	signal = 0
	"""	 
	### ここで売買条件を指定します。 ###
	# signal 売買シグナル 0:購入/売却無し, 1:購入, -1:売却
	# is_position 現在のポジション True:保持している, False:保持していない
	# prices ロウソク足
	# bolinger_std ボリンジャーバンド
	# macd MACD
	# sma SMA
	# trand_high 下降トレンドライン
	# trand_low 上昇トレンドライン

	### テクニカル分析の参考にした記事 ###
	# ロウソク足データ取得
	# https://lazzzy.co.jp/crypto/how_to_get_bitcoin_candle_data_from_bitbank/
	# トレンドライン
	# https://qiita.com/siruku6/items/c30fa5be0332c642d8d7
	# MACD
	# https://ichi.pro/python-de-no-macd-niyoru-arugorizumu-torihiki-30955601833243
	# ボリンジャーバンド
	# https://kusacurrency.com/trading/bolinger-band/
	"""
	return signal

while True:
	try:
		# 日付取得
		dt_now = datetime.datetime.now()
		today = datetime.date.today()
		yesterday = today-timedelta(days=1)
		
		# 実行時間を調整
		if (int(dt_now.minute) != 0 and int(dt_now.minute) % 15 > 1):
			time.sleep(5)
			continue
		
		# 日付調整(09:00までは前日分)
		if (dt_now.hour < 9):
			target_day = yesterday
		else:
			target_day = today
		day_from = today-timedelta(data_acquisition_period + 1) # 1日余分にデータ取得する
		day_to = target_day
		print('【実行時間】'+str(dt_now))

		# ロウソク足データを取得
		candle = get_candles(day_from, day_to, pair, candle_type)

		# ロウソク足データのチェック
		is_candle_check = candles_check(candle, continue_count)
		if not is_candle_check :
			# 正常に取得できなかった場合は2秒待って再度取得
			time.sleep(2)
			continue_count += 1
			continue
		# コンティニューを0に更新
		continue_count = 0

		candle_close = candle['Close']
		candle_time = candle['UnixTime']

		# 直近のロウソク足データ出力
		print(candle_close.iloc[-3::])

		# smaライン生成
		sma = candle_close.rolling(window=sma_line).mean()

		# トレンドライン生成
		candle = candle.append(candle.iloc[-1::]).reset_index(drop=True)
		candle['time_id']= candle.index + 1
		trand_high, trand_low = get_trendlines(candle, trade_line)

		# ボリンジャーバンド生成
		bolinger_average20, bolinger_std, bolinger_p2sigm, bolinger_m2sigm = get_bolinger(candle_close)

		# MACD作成
		macd = get_macd(candle_close, slow_ema, fast_ema, smooth)
		macd.tail()

		# tickerの保有チェック
		is_position = False
		position = bitbank.position
		if (ticker in position):
			print('保有ポジション：' + str(position))
			# tickerを1000円以上保有しているかチェック
			if ((position[ticker] * bitbank.last(pair)) > 1000) :
				is_position = True
				print('最後に購入したレート：' + str(bitbank.check_ex_rate(pair)))
		# 売買チェック
		signal = buy_sell_judgment(is_position, candle_close, bolinger_std, macd, sma, trand_high, trand_low)

		if (signal == -1):
			##########################
			# 売却実行
			##########################
			params={
				'pair':pair,
				'amount':position[ticker],
				'side':'sell',
				'type':'market'
			}
			r = bitbank.order(params)
			# 売却後のポジション
			position = bitbank.position
			# メッセージ作成
			sell_message = ticker + '売却単価@' + pair + '：' + str(bitbank.last(pair)) + '円'
			ex_rate_message = ticker + '最後の購入単価@' + pair + '：' + str(bitbank.check_ex_rate(pair)) + '円'
			position_message = '現在のポジション：' + ", ".join(["{0}={1}".format(key, value) for (key, value) in position.items()])
			print(sell_message)
			print(ex_rate_message)
			print(position_message)
			# LINE送信
			linebot.send(sell_message)
			linebot.send(ex_rate_message)
			linebot.send(position_message)

		elif (signal == 1):
			##########################
			# 購入実行
			##########################
			now_pair = int(bitbank.last(pair))
			# 成行のため保有金額の70%をamountに設定
			amount = round((int(position['jpy']) / int(now_pair))*0.7, 3)
			params = {
				'pair': pair,
				'amount': amount,
				'side': 'buy',
				'type': 'market'
			}
			r = bitbank.order(params)
			# 購入後のポジション
			position = bitbank.position
			# メッセージ作成
			message = ticker + '購入単価@' + pair + '：' + str(bitbank.check_ex_rate(pair)) + '円'
			position_message =  '現在のポジション：' + ", ".join(["{0}={1}".format(key, value) for (key, value) in position.items()])
			print(message)
			print(position_message)
			# LINE送信
			linebot.send(message)
			linebot.send(position_message)

		# 14分間一時停止
		time.sleep(60*14)

	except:
		# エラー内容出力
		print('=== エラー内容 ===')
		traceback.print_exc()
		# 何か例外が生じた際はLINE通知を飛ばしてBotを停止する
		linebot.send('自動売買APIでエラーが発生したため処理を終了しました')
		sys.exit()
