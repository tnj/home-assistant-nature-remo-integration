# Home Assistant 用 Nature Remo インテグレーション

[Nature Remo](https://nature.global/) シリーズ向けの Home Assistant インテグレーションです。
[Nature Remo Cloud API](https://developer.nature.global/) を利用して実装されており、
将来的に Home Assistant core への取り込みを目指しています(このリポジトリでは
カスタムコンポーネントとして開発しています。詳細は
[docs/CORE_SUBMISSION.md](docs/CORE_SUBMISSION.md) を参照してください)。

## 機能

| Nature Remo | Home Assistant |
| --- | --- |
| エアコン | `climate` — 運転モード、設定温度、風量、上下・左右スイング |
| テレビ | `remote`(全ボタン送信)+ 放送切替・入力切替ボタン |
| 照明 | `light`(オン/オフ)+ 常夜灯・全灯・明るさボタン用 `button` |
| 学習リモコン(カスタム赤外線家電) | 学習した信号ごとに 1 つの `button` |
| 内蔵センサー | `sensor` — 温度、湿度、照度、最終検知(人感) |
| センサーの校正 | `number` — 温度・湿度のオフセット |
| Remo E / E lite スマートメーター | `sensor` — 瞬時電力、買電量・売電量(エネルギーダッシュボード対応) |

## インストール(手動・プレリリース)

1. クライアントライブラリを Home Assistant の Python 環境にインストールします:
   `pip install aionatureremo`(PyPI リリース前は `pip install -e lib/aionatureremo`)。
2. `custom_components/nature_remo/` を `<config>/custom_components/` にコピーします。
3. Home Assistant を再起動します。

## 設定

1. <https://home.nature.global/> でパーソナルアクセストークンを発行します。
2. Home Assistant で **設定 → デバイスとサービス → インテグレーションを追加 → Nature Remo** を選択します。
3. トークンを貼り付けます。トークンが無効化された場合は自動的に再認証が促されます。

## 既知の制限

- Cloud API にはプッシュ通知の仕組みがないため、状態は 60 秒ごとにポーリングします
  (API の利用上限は 5 分あたり 30 リクエスト)。
- 人感センサーは「最終検知」のタイムスタンプとして公開されます。API が返すのは
  直近の検知情報のみのため、リアルタイムの motion バイナリセンサーは実現できません。
- 一部のエアコンはオートモードで相対温度(`-2`〜`+2`)を返しますが、そのまま数値として表示します。
- 家電本体の物理リモコンによる状態変更は Nature 側からも本インテグレーションからも
  検知できません。

## 開発

```bash
uv sync          # ワークスペースをセットアップ
uv run pytest    # ライブラリ・インテグレーションのテストを実行
uv run ruff check . && uv run mypy
```

## ライセンス

MIT — [LICENSE](LICENSE) を参照してください。Nature 社とは関係がありません。
