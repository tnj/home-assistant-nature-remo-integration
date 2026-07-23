# Home Assistant 用 Nature Remo インテグレーション

[Nature Remo](https://nature.global/) シリーズ向けの Home Assistant インテグレーションです。
[Nature Remo Cloud API](https://developer.nature.global/) を利用して実装されており、
将来的に Home Assistant core への取り込みを目指しています(このリポジトリでは
カスタムコンポーネントとして開発しています。詳細は
[docs/CORE_SUBMISSION.md](docs/CORE_SUBMISSION.md) を参照してください)。

## 機能

| Nature Remo | Home Assistant |
| --- | --- |
| エアコン | `climate` — 運転モード、設定温度、風量、上下・左右スイング。固定ボタン(スイング/チルト等)は `button`、リモコン側ステート(内部クリーン等)は `switch` |
| テレビ | API が列挙する全ボタンを `button` エンティティ化(電源・入力切替・チャンネル±・音量±のみ既定で有効、他はワンクリックで有効化)。電源はトグル信号(機器仕様として離散的な ON/OFF 信号は存在しない) |
| 照明 | `light`(オン/オフ)+ 常夜灯・全灯・明るさボタン用 `button` |
| 学習リモコン(カスタム赤外線家電) | 学習した信号ごとに 1 つの `button` |
| 内蔵センサー | `sensor` — 温度、湿度、照度、最終検知(人感) |
| センサーの校正 | `number` — 温度・湿度のオフセット |
| Remo E / E lite スマートメーター | `sensor` — 瞬時電力、買電量・売電量(エネルギーダッシュボード対応) |

## インストール

### HACS(推奨)

HACS のデフォルトストアに掲載されるまでは、カスタムリポジトリとして追加します:

1. HACS → 右上メニュー → **カスタムリポジトリ**
2. リポジトリ: `https://github.com/tnj/home-assistant-nature-remo-integration`、
   タイプ: **Integration** で追加
3. 一覧から **Nature Remo** をインストールし、Home Assistant を再起動

以後の更新はリリースのたびに HACS 経由で届きます。クライアントライブラリ
[aionatureremo](https://pypi.org/project/aionatureremo/) は manifest 経由で自動インストールされます。

### 手動

1. `custom_components/nature_remo/` を `<config>/custom_components/` にコピーします。
2. Home Assistant を再起動します(`aionatureremo` は自動インストールされます)。

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
- 5 分あたり 30 リクエストの上限は **Nature アカウント単位**です。同じアカウントで
  他の Nature Remo 連携を併用すると枠を取り合い、断続的に unavailable になります。
  アカウントごとに連携は 1 つに絞ってください。

## 開発

```bash
uv sync          # ワークスペースをセットアップ
uv run pytest    # ライブラリ・インテグレーションのテストを実行
uv run ruff check . && uv run mypy
```

## ライセンス

MIT — [LICENSE](LICENSE) を参照してください。Nature 社とは関係がありません。
