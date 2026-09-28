"""
監控台股加權指數(^TWII)是否「跌破」或「站上」20日均線(MA20)，
一旦發生就寄送 Email 通知。

設計重點：
- 每次執行都重新下載近期收盤價，用同一批資料算出「今天」與「昨天」
  的 MA20，比較兩天的相對位置變化，藉此判斷是否剛好在今天發生穿越。
  這樣就不需要額外保存狀態(state)，很適合放在 GitHub Actions 這種
  「每次執行都是全新環境」的排程上跑。
- 只有「真的發生穿越」的那一天才會寄信，不會每天在均線下方就一直洗版。

環境變數(由 GitHub Actions 的 Secrets 注入)：
    GMAIL_USER          寄件用的 Gmail 帳號
    GMAIL_APP_PASSWORD   Gmail 應用程式密碼(不是登入密碼，見 README)
    MAIL_TO              收件信箱，可用逗號分隔多個
"""

import os
import smtplib
import sys
from email.mime.text import MIMEText
from email.utils import formatdate

import yfinance as yf

TICKER = "^TWII"        # 台灣加權指數
MA_WINDOW = 20            # 均線天數
LOOKBACK_DAYS = "3mo"    # 抓多久的歷史資料，足夠算出前後兩天的 MA20 即可


def fetch_recent_close():
    """抓取最近的收盤價序列，回傳一個依日期排序的 pandas Series。"""
    df = yf.download(TICKER, period=LOOKBACK_DAYS, interval="1d", progress=False)
    if df.empty:
        raise RuntimeError("抓不到資料，請確認網路連線或 yfinance 是否正常")
    close = df["Close"].dropna()
    close = close.squeeze()  # 避免有時候回傳的是單欄 DataFrame
    return close


def detect_cross(close):
    """
    比較「今天」與「昨天」收盤價相對於 MA20 的位置，
    回傳事件字串：'break_down' / 'break_up' / None
    """
    ma = close.rolling(window=MA_WINDOW).mean()

    if len(close) < MA_WINDOW + 1:
        raise RuntimeError("歷史資料不足以計算 MA20，請拉長 LOOKBACK_DAYS")

    today_close, yesterday_close = close.iloc[-1], close.iloc[-2]
    today_ma, yesterday_ma = ma.iloc[-1], ma.iloc[-2]

    today_date = close.index[-1].strftime("%Y-%m-%d")

    was_above = yesterday_close >= yesterday_ma
    now_above = today_close >= today_ma

    event = None
    if was_above and not now_above:
        event = "break_down"
    elif (not was_above) and now_above:
        event = "break_up"

    return {
        "event": event,
        "date": today_date,
        "today_close": float(today_close),
        "today_ma20": float(today_ma),
    }


def send_mail(subject: str, body: str):
    gmail_user = os.environ["GMAIL_USER"]
    gmail_app_password = os.environ["GMAIL_APP_PASSWORD"]
    mail_to = os.environ["MAIL_TO"]

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = gmail_user
    msg["To"] = mail_to
    msg["Date"] = formatdate(localtime=True)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_app_password)
        server.sendmail(gmail_user, [x.strip() for x in mail_to.split(",")], msg.as_string())


def main():
    close = fetch_recent_close()
    result = detect_cross(close)

    print(f"日期: {result['date']}  收盤: {result['today_close']:.2f}  "
          f"MA20: {result['today_ma20']:.2f}  事件: {result['event']}")

    if result["event"] is None:
        print("今天沒有發生穿越，不寄信。")
        return

    if result["event"] == "break_down":
        subject = f"[大盤警報] 加權指數跌破20日均線 ({result['date']})"
        action = "跌破"
    else:
        subject = f"[大盤警報] 加權指數站上20日均線 ({result['date']})"
        action = "站上"

    body = (
        f"台灣加權指數(^TWII) 在 {result['date']} 收盤 {action} 20日均線。\n\n"
        f"收盤價：{result['today_close']:.2f}\n"
        f"MA20：{result['today_ma20']:.2f}\n"
    )

    send_mail(subject, body)
    print("已寄出通知信。")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"執行失敗: {e}", file=sys.stderr)
        sys.exit(1)
