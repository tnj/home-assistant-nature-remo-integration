# Nature Remo × Home Assistant 統合 — 設計書

- 日付: 2026-07-18
- ステータス: 設計プレゼン承認済み（2026-07-18）・スペック文書レビュー待ち
- 目的: Nature Remo Cloud API の全機能をカバーする Home Assistant 統合を、**HA コア（公式リポジトリ）への登録を前提とした品質**で新規開発する。HACS 配布は目的としない。

## 1. 背景と前提

- HA コアに Nature Remo 統合は存在せず、過去のコア PR 試行もゼロ。home-assistant/brands にも未登録。
- 既存 PyPI クライアント `nature-remo` は同期式・2021年からメンテ停止のためコア要件（PyPI 外部ライブラリ、async 推奨）を満たせない。**新規 async ライブラリの開発が必須**。
- 参考実装: hannoeru/hass-nature-remo（MIT、構造・テストの参考可）。NaNaLinks/homeassistant_nature_remo は**ライセンスなしのためコード流用禁止**（設計参考のみ）。
- Matter 対応（Remo nano / Lapis）は基本的な冷暖房のみで、IR 家電・スマートメーター・センサー群・旧機種はカバーしない。クラウド統合と補完関係にあり、本統合の価値を損なわない。

### ユーザー確認済みの決定事項

| 論点 | 決定 |
|---|---|
| リポジトリ構成 | `custom_components/` 型モノレポ（開発・実機検証しやすく、コア PR 時にコピー移植） |
| API クライアント | 新規 async ライブラリ `aionatureremo` をリポジトリ内で開発、将来 PyPI 公開 |
| TV の表現 | `remote` エンティティ + 入力切替 `select` |
| 人感センサー | **timestamp センサー**（最終検知時刻）。ポーリングでリアルタイム性がないため binary_sensor 化はしない |
| アプローチ | 全部入り + 単一コーディネーター（案1） |

## 2. Nature Remo Cloud API 前提（調査確定値）

- ベース URL: `https://api.nature.global`、認証: `Authorization: Bearer {個人アクセストークン}`（https://home.nature.global で発行）。OAuth2 は法人限定のため対象外。
- **プッシュ機構なし。ポーリングのみ。**
- レート制限: **30 リクエスト / 5 分 / アカウント**。`X-Rate-Limit-Limit / -Remaining / -Reset` ヘッダーあり。超過で HTTP 429。
- 使用エンドポイント:
  - `GET /1/users/me` — 接続検証・unique_id（`{id, nickname}`）
  - `GET /1/devices` — Remo 本体とセンサー値（`newest_events`: `te`温度 / `hu`湿度 / `il`明るさ(相対値) / `mo`人感(val=1固定、created_at が検知時刻)）
  - `GET /1/appliances` — 家電一覧（`type`: AC / TV / LIGHT / IR / EL_SMART_METER ほか）。スマートメーターの ECHONET Lite プロパティも内包（10進表現）
  - `POST /1/appliances/{id}/aircon_settings` — body: `temperature, temperature_unit, operation_mode, air_volume, air_direction, air_direction_h, button`。**安全のため常に現在設定全体 + 変更フィールドを送る**（v2 spec は全フィールド required）。応答は新しい設定全体
  - `POST /1/appliances/{id}/tv` / `POST /1/appliances/{id}/light` — body `{button}`。応答は新しい state
  - `POST /1/signals/{id}/send` — 空 body、IR 送信
  - `POST /1/devices/{id}/temperature_offset` / `humidity_offset` — body `{offset}`(int)。応答は Device
- AC の癖:
  - モード: `cool / warm / dry / blow / auto`（`warm`=暖房、`blow`=送風）。**電源 OFF はモードでなく `settings.button: "power-off"`**（`""` = ON）。`settings.mode` は OFF 中も直前モードを保持
  - `aircon.range.modes[モード]` = `{temp[], vol[], dir[], dirh[]}`（そのモードで許容される値リスト。空/null あり）
  - auto モードの temp は「-2」「+2」のような**相対値の機種がある**（既知の癖。float パースで受容し、既知の制約としてドキュメント化）
- スマートメーター（`appliance.smart_meter.echonetlite_properties`、epc は10進整数）:

  | name | EPC | 意味 |
  |---|---|---|
  | coefficient | 211 (0xD3) | 積算値の係数（欠落時は 1） |
  | normal_direction_cumulative_electric_energy | 224 (0xE0) | 買電積算（生カウンタ） |
  | cumulative_electric_energy_unit | 225 (0xE1) | 単位コード |
  | reverse_direction_cumulative_electric_energy | 227 (0xE3) | 売電積算（生カウンタ） |
  | measured_instantaneous | 231 (0xE7) | 瞬時電力 [W]（符号付き、負=売電） |

  - `kWh = 生カウンタ × coefficient × 単位倍率(E1)`。単位倍率は**査表**: `{0:1, 1:0.1, 2:0.01, 3:0.001, 4:0.0001, 10:10, 11:100, 12:1000, 13:10000}`（`10^-n` 式は 10〜13 で誤るため使用禁止）
  - E1 が欠落した場合は積算エネルギーセンサーを生成しない。E3 欠落時は売電センサーのみ省略
- エラー: formal なエラースキーマなし。**HTTP ステータスで分岐**（401 認証 / 429 レート / 4xx/5xx）

## 3. リポジトリ構成（uv ワークスペース・モノレポ）

```
├── pyproject.toml                  # workspace ルート（dev 依存: HA, pytest, ruff, mypy 等）
├── lib/aionatureremo/              # async API クライアント（PyPI 公開前提・MIT）
│   ├── pyproject.toml              # hatchling、py.typed、requires-python >=3.12
│   ├── src/aionatureremo/
│   └── tests/                      # aioresponses による単体テスト
├── custom_components/nature_remo/  # HA 統合本体（コア PR 時にコピー移植）
│   ├── __init__.py  config_flow.py  coordinator.py  entity.py  const.py
│   ├── climate.py  sensor.py  light.py  remote.py  select.py  button.py  number.py
│   ├── diagnostics.py  manifest.json  strings.json  icons.json  quality_scale.yaml
│   └── translations/en.json, ja.json
├── tests/                          # 統合テスト (pytest-homeassistant-custom-component)
│   └── fixtures/                   # 実 API 形状の JSON
├── docs/                           # 本設計書、CORE_SUBMISSION.md
├── .github/workflows/ci.yml        # ruff / mypy / pytest ×2 / hassfest
├── LICENSE (MIT)  README.md (EN)  README.ja.md
```

- コード・コメント・strings.json は英語（コア要件）。README は日英併記。
- ドメイン: `nature_remo`。custom 用 manifest には `version` を含め、コア移植時に削除して `quality_scale` を追加（差分はこの程度に収める）。

## 4. API クライアント `aionatureremo`

- **設計方針**: aiohttp `ClientSession` 注入型（HA の `async_get_clientsession` を受ける。Platinum `inject-websession` 対応）。全メソッド async。`py.typed` で完全型付け。依存は aiohttp のみ（pydantic 不使用 — HA との互換リスク回避。plain dataclass + 明示パース）。
- **公開 API**:
  - `NatureRemoClient(token, session, *, base_url=...)`
  - `async get_user() -> User`
  - `async get_devices() -> list[Device]`
  - `async get_appliances() -> list[Appliance]`
  - `async set_aircon_settings(appliance_id, *, operation_mode=..., temperature=..., air_volume=..., air_direction=..., air_direction_h=..., button=...) -> AirconSettings`
  - `async send_tv_button(appliance_id, button) -> TVState`
  - `async send_light_button(appliance_id, button) -> LightState`
  - `async send_signal(signal_id) -> None`
  - `async set_temperature_offset(device_id, offset) -> Device` / `set_humidity_offset(...)`
- **モデル** (dataclass): `User / Device / SensorValue / Appliance / ApplianceModel / AirconRange / AirconSettings / TV / TVState / Light / LightState / Signal / SmartMeter / EchonetLiteProperty`。`from_dict()` classmethod で防御的にパース（未知フィールド無視、任意フィールドの欠落は None/デフォルト。ただし `id`/`epc` 等の必須識別子は fail-fast — API が保証するキーであり、デフォルト化は下流のインデックスを静かに壊すため）。
- **SmartMeter ヘルパー**: `instantaneous_power_w -> int | None`、`cumulative_energy_kwh -> float | None`、`cumulative_energy_reverse_kwh -> float | None`（§2 の査表・係数ロジックを内蔵）。
- **例外**: `NatureRemoError`（基底）/ `NatureRemoAuthError`(401) / `NatureRemoRateLimitError`(429、`reset` epoch 保持) / `NatureRemoApiError`(その他 4xx/5xx、status 保持) / `NatureRemoConnectionError`（ネットワーク層）。
- **レート制限追跡**: 全応答の `X-Rate-Limit-*` を読み `client.rate_limit: RateLimit(limit, remaining, reset)` として公開（先行実装にない改善点。統合側はログ・診断に使用）。
- **テスト**: aioresponses で全エンドポイント・全例外系・EPC 換算（単位コード 10〜13 含む）を単体テスト。
- **公開準備**: タグ push で PyPI へ自動公開する workflow（`dependency-transparency` 準拠）。PyPI 名 `aionatureremo` は公開時に空き確認（衝突時は `python-nature-remo-async` 等へフォールバック）。

## 5. 統合アーキテクチャ

### 5.1 セットアップとデータ

- `type NatureRemoConfigEntry = ConfigEntry[NatureRemoCoordinator]`、データは `entry.runtime_data`（Bronze `runtime-data`）。
- `async_setup_entry`: クライアント生成（共有セッション注入）→ coordinator `async_config_entry_first_refresh()`（`test-before-setup`）→ 各プラットフォームへ forward → 動的デバイス/stale 掃除のリスナー登録。
- `manifest.json`: `iot_class: cloud_polling`、`integration_type: hub`、`config_flow: true`、`requirements: ["aionatureremo==0.1.0"]`（実バージョンを記載。PyPI 公開前の開発中は、HA 環境へ `pip install -e lib/aionatureremo` しておけば要件充足済みと判定されインストールは走らない。この手順を README に記載）、`codeowners`、`loggers: ["aionatureremo"]`。

### 5.2 Config flow

- `async_step_user`: アクセストークン入力（`data_description` で home.nature.global での発行手順を案内）→ `get_user()` で検証（`test-before-configure`）→ `unique_id = user.id`、`_abort_if_unique_id_configured()`（複数アカウント対応・重複防止）→ タイトル = nickname。
- エラーキー: `invalid_auth`(401) / `cannot_connect`(接続・429) / `unknown`。エラー後の再入力から成功まで到達可能に（回復パス必須）。
- `async_step_reauth` / `reauth_confirm`: 新トークン検証後、**user.id が既存 entry と一致することを確認**（不一致は `wrong_account` abort）→ `async_update_reload_and_abort`。
- `async_step_reconfigure`: 同一フォームでトークン差し替え（同様のアカウント一致チェック）。
- options flow は**作らない**（ポーリング間隔のユーザー設定はコアで禁止）。`VERSION = 1, MINOR_VERSION = 1`。

### 5.3 Coordinator

- 単一 `NatureRemoCoordinator(DataUpdateCoordinator[NatureRemoData])`、`update_interval = 60秒`、コンストラクタに `config_entry` を渡す（現行コア要件）。
- `_async_update_data`: `get_devices()` → `get_appliances()` を直列 await（エラー帰属を決定的にするため。gather と同じく 2 コール/周期 × 5 周期 = 10 コール/5分、制限 30 の安全圏）→ `NatureRemoData(devices: dict[id, Device], appliances: dict[id, Appliance])`。
- 例外変換: `NatureRemoAuthError → ConfigEntryAuthFailed`（reauth 起動）/ `NatureRemoRateLimitError・NatureRemoConnectionError・NatureRemoApiError → UpdateFailed`（429 は reset 時刻をメッセージに含める）。
- **楽観的更新**: コマンド応答（aircon_settings / tv / light / offset の新状態）で coordinator データを書き換え `async_set_updated_data()` → UI 即時反映。次回ポーリングで真値と同期。

### 5.4 デバイスレジストリ

- Remo 本体: `identifiers={(DOMAIN, device.id)}`、`connections={(MAC, mac_address)}`、`manufacturer="Nature"`、`model=firmware_version の "/" 前`（例 "Remo"、"Remo-mini"）、`sw_version="/" 後`、`serial_number`、`configuration_url="https://home.nature.global/"`。
- アプライアンス: `identifiers={(DOMAIN, appliance.id)}`、`via_device=(DOMAIN, device.id)`、`name=nickname`、`manufacturer/model` は `appliance.model` から（null 可）。
- **動的対応**（Gold 先取り）: ポーリングで新規デバイス/アプライアンス検出時にエンティティ自動追加（プラットフォームごとに known-ids + coordinator リスナー）。消えたものはデバイスレジストリから自動削除 + `async_remove_config_entry_device` 実装。

### 5.5 エラー処理・並列制御

- コマンド失敗（サービス呼び出し中の API エラー）は `HomeAssistantError` に変換して raise（メッセージにレート制限の reset を含める。将来 `exception-translations` 対応）。無効なコマンド名・選択肢は `ServiceValidationError`。
- `PARALLEL_UPDATES`: 読み取り専用プラットフォーム（sensor）= 0、操作系（climate / light / remote / select / button / number）= 1（コマンド直列化でレート制限とIR干渉を緩和）。
- ログ: 429 発生時は warning（reset 時刻付き）。unavailable 遷移は coordinator 標準機構に委譲。

## 6. エンティティ仕様

共通: `_attr_has_entity_name = True`、`CoordinatorEntity` 継承の共通基底 `NatureRemoEntity`（`entity.py`）、`translation_key` ベースの命名、unique_id は下表。

### 6.1 Remo 本体（`GET /1/devices` 起点、キー存在で生成判定）

| エンティティ | unique_id | 仕様 |
|---|---|---|
| sensor 温度 (`te`) | `{device_id}_temperature` | TEMPERATURE / °C / MEASUREMENT / precision 1 |
| sensor 湿度 (`hu`) | `{device_id}_humidity` | HUMIDITY / % / MEASUREMENT / precision 0 |
| sensor 明るさ (`il`) | `{device_id}_illuminance` | **device_class・単位なし**（lx でない相対値のため）/ MEASUREMENT |
| sensor 最終人感検知 (`mo`) | `{device_id}_last_motion` | TIMESTAMP。`mo.created_at` をそのまま公開 |
| number 温度補正 | `{device_id}_temperature_offset` | CONFIG / BOX / -10〜10 / step 1 / set で POST→応答で楽観的更新 |
| number 湿度補正 | `{device_id}_humidity_offset` | CONFIG / BOX / -20〜20 / step 1（範囲は実機検証で調整） |

### 6.2 AC → climate

- `hvac_modes`: `aircon.range.modes` のキーを写像（`cool→COOL, warm→HEAT, dry→DRY, blow→FAN_ONLY, auto→AUTO`）+ `OFF`。
- 状態: `settings.button == "power-off"` なら `OFF`、それ以外は `settings.mode` の写像。
- `supported_features`（動的）: `TURN_ON | TURN_OFF` 常時。現在モードの `temp` リストが非空なら `TARGET_TEMPERATURE`、`vol` 非空なら `FAN_MODE`、`dir` 非空なら `SWING_MODE`、`dirh` 非空なら `SWING_HORIZONTAL_MODE`（HA 2024.12+）。
- `min_temp / max_temp / target_temperature_step`: **全モードの絶対温度リストの和集合**から導出（step は隣接差の最小値、既定 1.0）。HA コアは `set_temperature` をエンティティのモード切替前に min/max で検証するため、モード別レンジ（不連続あり）だと温度+モード同時指定が弾かれる。モード別の制約は送信時の許容リスト吸着で担保。auto モードの相対値リスト（`+2` 等、`+` 接頭辞で判定）は和集合から除外。
- `fan_modes / swing_modes / swing_horizontal_modes`: API の生値をそのまま提示（`auto`, `1`〜, `swing` 等。翻訳はしない）。
- `current_temperature / current_humidity`: 紐づく Remo 本体（`appliance.device.id`）の `te` / `hu`。
- `temperature_unit`: `settings.temp_unit == "f"` → °F、それ以外 °C。
- コマンド: **常に現在設定全体 + 変更点を送信**。`set_hvac_mode(OFF)` → `button="power-off"`、他モード → `operation_mode` 変更 + `button=""`（ON 復帰）。`set_temperature` は許容リストへスナップ、`ATTR_HVAC_MODE` 同時指定に対応。応答で楽観的更新。
- auto モードの相対温度（"+2" 等）は float パースで受容し、README に既知の制約として記載。

### 6.3 TV → remote + select

- remote: `unique_id = {appliance_id}`、`assumed_state = True`、`is_on = None`。
  - `send_command(command, num_repeats, delay_secs)`: 各コマンド名を `tv.buttons[].name` と照合（不明は `ServiceValidationError`）→ `POST /tv`。repeats/delay を尊重。
  - `turn_on / turn_off`: `power` ボタン送信（トグル前提）。`power` ボタンが無い機種では `ServiceValidationError`（remote の turn_on/off はベース機能のため無効化不可）。
- select 入力切替: `tv.state.input`（`t`/`bs`/`cs`）を current に、**対応するボタンが `tv.buttons` に2つ以上存在する場合のみ生成**（1択の select は無意味なため）。option 選択でそのボタンを送信し、`state.input` を楽観的更新。状態表示は translation（地上波/BS/CS）。**実機でボタン名を要検証**（検証ポイント §9）。

### 6.4 LIGHT → light + button

- light: `is_on = state.power == "on"`。`ColorMode.ONOFF` のみ。`turn_on → "on"`、`turn_off → "off"` ボタン送信 + 楽観的更新。`on`/`off` が無く `onoff` のみの機種はトグル送信 + `assumed_state = True`。
- 追加ボタン（`on`/`off`/`onoff` 以外、例 `on-100`, `night`, `bright-up`, `bright-down`, `colortemp-up`, `colortemp-down`, `on-favorite`）: 1つずつ button エンティティ化。既知名は translation_key、未知名はラベルをそのまま名前に。unique_id `{appliance_id}_button_{name}`。

### 6.5 IR → button

- 学習済みシグナルごとに button。`unique_id = {appliance_id}_signal_{signal_id}`、名前はシグナル名（ユーザー定義文字列をそのまま）。press → `POST /1/signals/{id}/send`。

### 6.6 EL_SMART_METER → sensor ×3

| エンティティ | unique_id | 仕様 |
|---|---|---|
| 瞬時電力 | `{appliance_id}_instantaneous_power` | POWER / W / MEASUREMENT / 符号付き（負=売電） |
| 買電積算 | `{appliance_id}_cumulative_energy_normal` | ENERGY / kWh / **TOTAL_INCREASING** / §2 の換算式 |
| 売電積算 | `{appliance_id}_cumulative_energy_reverse` | 同上（EPC 227 が存在する場合のみ） |

→ HA エネルギーダッシュボードにそのまま登録可能。

## 7. テスト戦略

- **ライブラリ** (`lib/aionatureremo/tests/`): aioresponses。認証ヘッダー、全エンドポイント、401/429/5xx→例外、レート制限ヘッダー追跡、EPC 換算表（コード 0〜4, 10〜13）、aircon 送信ペイロードの組み立て。
- **統合** (`tests/`): pytest-homeassistant-custom-component。実 API 形状の JSON フィクスチャ（Remo 3 / mini / E + AC / TV / LIGHT / IR / スマートメーターを含む代表構成）。
  - config flow: 正常系 CREATE_ENTRY、invalid_auth / cannot_connect / unknown → 回復して成功、重複 abort、reauth 成功 / wrong_account、reconfigure。**100% カバレッジ必須**。
  - init: セットアップ成功、初回失敗 → ConfigEntryNotReady、認証失敗 → reauth flow 起動、unload。
  - 各プラットフォーム: syrupy スナップショット + コマンド系（climate の全 set 系・ON/OFF、remote の send_command / 無効名、light、select、button、number）、楽観的更新の検証、429 時の HomeAssistantError、動的追加・stale 削除、mo タイムスタンプ。
- **CI** (GitHub Actions): ruff check + format --check、mypy（lib は strict）、pytest（lib / 統合）、home-assistant/actions hassfest 検証。

## 8. コア提出戦略（詳細は docs/CORE_SUBMISSION.md に整備）

1. `aionatureremo` を PyPI へ公開（タグ→自動リリース）
2. home-assistant/brands へ icon/logo PR（icon.png 256/512）
3. コア PR #1: config flow + **sensor** のみ（Bronze 達成、quality_scale.yaml 同梱）— コアの「単一プラットフォームから」方針に適合
4. 後続 PR: climate → light / remote / select / button / number → diagnostics・reauth 等
5. 各 PR に並行して home-assistant.io へドキュメント PR
- custom→core 差分: manifest から `version` 削除・`quality_scale: bronze` 追加、テストの import 調整のみに収まる構造を維持する。

## 9. 検証ポイント（実機確認が必要な項目）

1. TV の入力切替ボタンの実名称（`t`/`bs`/`cs` か否か）→ select の生成条件を確定
2. 温度/湿度オフセットの API 許容範囲
3. LIGHT の `onoff` のみ機種の挙動
4. auto モード相対温度の実データ形状
5. firmware_version のモデル別プレフィックス（model 表示の妥当性）

## 10. スコープ外（v1）と将来拡張

- EL 系その他（太陽光 / 蓄電池 / EV 充放電 / 給湯器）、QRIO_LOCK / SESAME / MORNIN_PLUS、FLOOR_HEATER（aircon_settings 互換のため将来 climate 追加が容易）、LIGHT_PROJECTOR、BLE マクロ、複数ホーム API、全戸電力タイムシリーズ、appliance 検出 API、ECHONET refresh/set（20秒スロットル・法人プラン）、Local API、OAuth2。
- 将来: `exception-translations` / `repair-issues` などの Gold/Platinum ルール、Remo E の全戸エネルギー時系列。

## 11. リスクと対応

| リスク | 対応 |
|---|---|
| レート制限（コマンド連打で 30/5分超過） | PARALLEL_UPDATES=1、429 の reset をエラーメッセージ化、レート追跡をログ/診断に出す |
| API の undocumented な揺れ（エラーボディ等） | ステータスコードのみで分岐、パースは防御的に |
| pytest-homeassistant-custom-component と HA のバージョン整合 | CI で HA バージョンを pin し、更新は Renovate 的に追従 |
| PyPI 名の衝突 | 公開時に確認、代替名を用意 |
| 実機依存の未確定仕様（§9） | 実装中にユーザーの実機で確認し、確定後にテストフィクスチャへ反映 |
