"""Send the published release and small APKs without logging bot credentials."""
import html
import json
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
import uuid


def call_api(token, method, fields, document=None):
    if document is None:
        data = urlencode(fields).encode()
        content_type = 'application/x-www-form-urlencoded'
    else:
        boundary = uuid.uuid4().hex
        chunks = []
        for name, value in fields.items():
            chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        filename = document.name.replace('"', '').replace('\r', '').replace('\n', '')
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="document"; filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
        chunks.extend([document.read_bytes(), f'\r\n--{boundary}--\r\n'.encode()])
        data = b''.join(chunks)
        content_type = f'multipart/form-data; boundary={boundary}'
    request = Request(f'https://api.telegram.org/bot{token}/{method}', data=data,
                      headers={'Content-Type': content_type})
    for attempt in range(3):
        try:
            with urlopen(request, timeout=180) as response:
                result = json.load(response)
        except HTTPError as error:
            try:
                result = json.loads(error.read())
            except (ValueError, OSError):
                raise RuntimeError(f'Telegram HTTP error {error.code}') from None
        except (URLError, TimeoutError, OSError):
            # Do not print exceptions containing the token-bearing request URL.
            raise RuntimeError('Telegram network request failed') from None
        if result.get('ok'):
            return
        if result.get('error_code') == 429 and attempt < 2:
            time.sleep(min(int(result.get('parameters', {}).get('retry_after', 5)), 30))
            continue
        raise RuntimeError(f"Telegram API rejected request (code {result.get('error_code', 'unknown')})")


def main():
    token = os.environ.get('BOT_TOKEN', '')
    if not token:
        raise RuntimeError('Missing TELEGRAM_BOT_TOKEN secret')
    chat_id = os.environ['CHAT_ID']
    tag = os.environ['RELEASE_TAG']
    repo = os.environ['REPO']
    url = f'https://github.com/{repo}/releases/tag/{quote(tag, safe="")}'
    text = (f'<b>AppMarket 更新已发布</b>\n'
            f'版本：<code>{html.escape(tag)}</code>\n'
            f'<a href="{html.escape(url, quote=True)}">下载 APK · 查看更新内容</a>')
    call_api(token, 'sendMessage', {'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})
    for apk in sorted(Path('release-assets').glob('*.apk')):
        if apk.stat().st_size > 50_000_000:
            print(f'{apk.name}: exceeds Telegram upload limit; use release link.')
            continue
        time.sleep(1)
        call_api(token, 'sendDocument', {'chat_id': chat_id, 'caption': apk.name[:1024]}, apk)
    print('Telegram notification sent.')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as error:
        print(f'::error::{error}', file=sys.stderr)
        sys.exit(1)
