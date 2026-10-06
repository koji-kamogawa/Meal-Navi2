import streamlit as st
import os
import json
import csv
import io
from openai import OpenAI

# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------
DEFAULT_INGREDIENTS = {
    "野菜": ["じゃがいも", "人参", "玉ねぎ", "キュウリ", "ブロッコリー", "トマト", "プチトマト", "ピーマン", "キャベツ", "ほうれん草", "レタス", "長ネギ", "白菜"],
    "肉類": ["牛肉ブロック", "牛肉スライス", "豚肉ブロック", "豚肉スライス", "鶏モモ肉", "鶏むね肉", "ハム", "ソーセージ", "塩鮭"],
    "その他": ["玉子", "豆腐", "乾燥ワカメ", "こんにゃく"],
    "調味料": ["醤油", "ソース", "味噌", "塩", "砂糖", "塩コショウ", "お酢", "みりん", "七味", "マヨネーズ", "ケチャップ", "チューブワサビ", "チューブ辛子", "チューブニンニク", "和風ドレッシング", "洋風ドレッシング", "オイスターソース", "鶏がらスープの素", "ほんだしの素"]
}

DEFAULT_USER_INFO = {
    "家族構成": "",
    "子供の年齢": "",
    "料理者の熟練度_和": "初心者",
    "料理者の熟練度_洋": "初心者",
    "料理者の熟練度_中": "初心者",
    "家族の好み_食材": "",
    "家族の苦手な料理・食材": "",
    "アレルギー": "",
    "家族の皆が好きな料理": "",
    "旬の野菜利用": True
}

SKILL_OPTIONS = ["初心者", "中級者", "上級者"]
UPLOADER_KEY = "user_info_csv_uploader"

# st.fragment が使えない古い Streamlit でも動くようにする
_fragment = (
    getattr(st, "fragment", None)
    or getattr(st, "experimental_fragment", None)
    or (lambda f: f)
)


# ---------------------------------------------------------------------------
# 状態管理（入力ウィジェットの key を唯一のデータ源にする）
# ---------------------------------------------------------------------------
def _ukey(field):
    return f"ui_{field}"


def _ikey(category):
    return f"ing_{category}"


def _parse_items(text):
    return [x.strip() for x in text.split(",") if x.strip()]


def init_session_state():
    for field, default in DEFAULT_USER_INFO.items():
        st.session_state.setdefault(_ukey(field), default)
    for category, items in DEFAULT_INGREDIENTS.items():
        st.session_state.setdefault(_ikey(category), ",".join(items))
    st.session_state.setdefault("menu_data", None)
    st.session_state.setdefault("menu_view", None)
    st.session_state.setdefault("show_menu", False)
    st.session_state.setdefault("csv_message", None)


def get_user_info():
    return {f: st.session_state.get(_ukey(f), d) for f, d in DEFAULT_USER_INFO.items()}


def get_ingredients():
    return {
        c: _parse_items(st.session_state.get(_ikey(c), ",".join(items)))
        for c, items in DEFAULT_INGREDIENTS.items()
    }


# ---------------------------------------------------------------------------
# ユーザー情報 CSV
# ---------------------------------------------------------------------------
def user_info_to_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["項目", "値"])
    for key, value in get_user_info().items():
        writer.writerow([key, value])
    for category, items in get_ingredients().items():
        writer.writerow([f"食材_{category}", ",".join(items)])
    return output.getvalue()


def on_user_csv_uploaded():
    """file_uploader の on_change コールバック。
    ウィジェット生成前に実行されるため、入力欄の値を安全に更新できる。
    （rerun のループ防止用キーや st.rerun() も不要）"""
    uploaded_file = st.session_state.get(UPLOADER_KEY)
    if uploaded_file is None:
        st.session_state.csv_message = None
        return
    try:
        content = uploaded_file.getvalue().decode("utf-8-sig")
        rows = list(csv.reader(io.StringIO(content)))
        if len(rows) < 2:
            st.session_state.csv_message = ("warning", "CSVにデータ行がありません。")
            return
        for row in rows[1:]:
            if len(row) < 2:
                continue
            key, value = row[0], row[1]
            if key.startswith("食材_"):
                category = key.replace("食材_", "", 1)
                if category in DEFAULT_INGREDIENTS:
                    st.session_state[_ikey(category)] = ",".join(_parse_items(value))
            elif key in DEFAULT_USER_INFO:
                if key == "旬の野菜利用":
                    st.session_state[_ukey(key)] = value.lower() == "true"
                elif key.startswith("料理者の熟練度_"):
                    if value in SKILL_OPTIONS:
                        st.session_state[_ukey(key)] = value
                else:
                    st.session_state[_ukey(key)] = value
        st.session_state.csv_message = ("success", "ユーザ情報を読み込みました。")
    except Exception as e:
        st.session_state.csv_message = ("error", f"CSV読み込みエラー: {e}")


# ---------------------------------------------------------------------------
# プロンプト / API
# ---------------------------------------------------------------------------
def build_prompt():
    info = get_user_info()
    ingredients = get_ingredients()
    prompt = f"""あなたはプロの栄養士兼料理研究家です。以下の条件に基づいて、1か月分（4週間、月曜日始まり）の夕食メニューを生成してください。
【家族情報】
- 家族構成: {info.get('家族構成', '')}
- 子供の年齢: {info.get('子供の年齢', '')}
- 料理者の熟練度: 和食={info.get('料理者の熟練度_和', '初心者')}, 洋食={info.get('料理者の熟練度_洋', '初心者')}, 中華={info.get('料理者の熟練度_中', '初心者')}
- 家族の好み（食材）: {info.get('家族の好み_食材', '')}
- 家族の苦手な料理・食材: {info.get('家族の苦手な料理・食材', '')}
- アレルギー: {info.get('アレルギー', '')}
- 家族の皆が好きな料理: {info.get('家族の皆が好きな料理', '')}
- 旬の野菜を利用: {'はい' if info.get('旬の野菜利用', True) else 'いいえ'}
【利用可能な食材】
- 野菜: {', '.join(ingredients.get('野菜', []))}
- 肉類: {', '.join(ingredients.get('肉類', []))}
- その他: {', '.join(ingredients.get('その他', []))}
- 調味料: {', '.join(ingredients.get('調味料', []))}
【生成ルール】
1. 各日の夕食に主菜と副菜を1品ずつ提案すること。
2. 主菜と副菜で同じ調理方法（揚げ物、煮物、焼き物、炒め物、蒸し物、和え物など）が重ならないようにすること。
3. カテゴリ（和洋中）が連続しないようにすること。
4. 使用する食材は、野菜から1～3種類、肉類から1種類、その他はメニューに応じて使用すること。
5. 調味料は登録されたもののみを使用すること。
6. 下ごしらえに時間がかかるメニューは土曜日・日曜日に提案すること。
7. マンネリ化しないよう、時々新しい提案をすること。その際、必要な食材があれば明記すること。
8. 各メニューには簡単なレシピ（材料と手順）を含めること。
9. 家族の苦手な料理・食材は絶対に使用しないこと。苦手な食材を含む料理は代替案を提案すること。
【出力形式】
以下のJSON形式で出力してください。必ず有効なJSONのみを返してください。
{{
  "weeks": [
    {{
      "week_number": 1,
      "days": [
        {{
          "day": "月曜日",
          "main_dish": {{
            "name": "料理名",
            "category": "和/洋/中",
            "cooking_method": "調理方法",
            "ingredients": ["食材1", "食材2"],
            "recipe": "簡単なレシピ"
          }},
          "side_dish": {{
            "name": "料理名",
            "category": "和/洋/中",
            "cooking_method": "調理方法",
            "ingredients": ["食材1", "食材2"],
            "recipe": "簡単なレシピ"
          }}
        }}
      ]
    }}
  ]
}}
"""
    return prompt


@st.cache_resource(show_spinner=False)
def _create_client(api_key):
    # OpenAI クライアント（内部の httpx / SSLコンテキスト生成が重い）を使い回す
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def get_deepseek_client():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        st.error("環境変数 DEEPSEEK_API_KEY が設定されていません。")
        return None
    return _create_client(api_key)


def generate_menu():
    client = get_deepseek_client()
    if not client:
        return None
    prompt = build_prompt()
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": "あなたはプロの栄養士兼料理研究家です。必ず有効なJSONのみを返してください。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=8000,
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        st.error(f"メニュー生成エラー: {e}")
        return None


# ---------------------------------------------------------------------------
# メニュー → CSV / 表示用データ（生成時に1回だけ作る）
# ---------------------------------------------------------------------------
def menu_to_csv(menu_data, weeks=4):
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["週", "曜日", "主菜名", "主菜カテゴリ", "主菜調理方法", "主菜食材", "主菜レシピ", "副菜名", "副菜カテゴリ", "副菜調理方法", "副菜食材", "副菜レシピ"])
    if not menu_data or "weeks" not in menu_data:
        return output.getvalue()
    for week in menu_data["weeks"][:weeks]:
        week_num = week.get("week_number", "")
        for day in week.get("days", []):
            day_name = day.get("day", "")
            main = day.get("main_dish", {})
            side = day.get("side_dish", {})
            writer.writerow([
                week_num, day_name,
                main.get("name", ""), main.get("category", ""), main.get("cooking_method", ""), ",".join(main.get("ingredients", [])), main.get("recipe", ""),
                side.get("name", ""), side.get("category", ""), side.get("cooking_method", ""), ",".join(side.get("ingredients", [])), side.get("recipe", "")
            ])
    return output.getvalue()


def _dish_markdown(label, dish):
    dish = dish or {}
    return (
        f"### {label}: {dish.get('name', '')}\n\n"
        f"カテゴリ: {dish.get('category', '')} / 調理方法: {dish.get('cooking_method', '')}\n\n"
        f"食材: {', '.join(dish.get('ingredients', []))}\n\n"
        f"レシピ: {dish.get('recipe', '')}"
    )


def build_menu_view(menu_data):
    """表示用Markdownと、ダウンロード用CSV(bytes)を事前計算する。"""
    days = []
    weeks = menu_data.get("weeks", []) if menu_data else []
    if weeks:
        for day in weeks[0].get("days", []):
            days.append((
                f"{day.get('day', '')}のメニュー",
                _dish_markdown("主菜", day.get("main_dish", {})),
                _dish_markdown("副菜", day.get("side_dish", {})),
            ))
    return {
        "days": days,
        "csv_1week": menu_to_csv(menu_data, weeks=1).encode("utf-8-sig"),
        "csv_4weeks": menu_to_csv(menu_data, weeks=4).encode("utf-8-sig"),
    }


# ---------------------------------------------------------------------------
# UI（フラグメント化：操作時にその部分だけ再実行される）
# ---------------------------------------------------------------------------
@_fragment
def render_sidebar_inputs():
    st.header("📋 家族情報入力")
    st.text_input("家族構成", key=_ukey("家族構成"), placeholder="例: 夫婦+子供2人")
    st.text_input("子供の年齢", key=_ukey("子供の年齢"), placeholder="例: 5歳, 8歳")

    st.subheader("料理者の熟練度")
    st.selectbox("和食", SKILL_OPTIONS, key=_ukey("料理者の熟練度_和"))
    st.selectbox("洋食", SKILL_OPTIONS, key=_ukey("料理者の熟練度_洋"))
    st.selectbox("中華", SKILL_OPTIONS, key=_ukey("料理者の熟練度_中"))

    st.text_area("家族の好み（食材）", key=_ukey("家族の好み_食材"), placeholder="例: 鶏肉好き、魚は苦手")
    st.text_area("家族の苦手な料理・食材", key=_ukey("家族の苦手な料理・食材"), placeholder="例: ピーマン、レバー、セロリ、辛い料理")
    st.text_area("アレルギーの有無", key=_ukey("アレルギー"), placeholder="例: 卵アレルギー")
    st.text_area("家族の皆が好きな料理", key=_ukey("家族の皆が好きな料理"), placeholder="例: カレー、ハンバーグ")
    st.checkbox("旬の野菜を利用する", key=_ukey("旬の野菜利用"))

    st.header("🥕 利用可能な食材")
    for category in DEFAULT_INGREDIENTS:
        with st.expander(f"{category}（クリックで編集）"):
            st.text_area(f"{category}（カンマ区切り）", key=_ikey(category))

    st.header("💾 ユーザ情報の保存・読み込み")
    st.download_button(
        "ユーザ情報をCSVでダウンロード",
        data=user_info_to_csv().encode("utf-8-sig"),
        file_name="user_info.csv",
        mime="text/csv",
    )
    st.file_uploader("ユーザ情報CSVをアップロード", type=["csv"],
                     key=UPLOADER_KEY, on_change=on_user_csv_uploaded)
    message = st.session_state.csv_message
    if message:
        getattr(st, message[0])(message[1])


@_fragment
def render_menu_results():
    view = st.session_state.menu_view
    if not view:
        return
    st.header("📅 1週間分の夕食メニュー")
    for title, main_md, side_md in view["days"]:
        with st.expander(title, expanded=True):
            col_a, col_b = st.columns(2)
            col_a.markdown(main_md)
            col_b.markdown(side_md)

    st.header("📥 CSVダウンロード")
    col_d1, col_d2 = st.columns(2)
    with col_d1:
        st.download_button("1週間分のメニューをCSVでダウンロード", data=view["csv_1week"],
                           file_name="menu_1week.csv", mime="text/csv")
    with col_d2:
        st.download_button("1か月分のメニューをCSVでダウンロード", data=view["csv_4weeks"],
                           file_name="menu_4weeks.csv", mime="text/csv")


def main():
    st.set_page_config(page_title="1週間夕食メニュー提案", layout="wide")
    init_session_state()

    st.title("🍽️ 共働き家庭のための夕食メニュー提案アプリ")
    st.markdown("家族情報を入力し、1週間分の夕食メニューを生成します。裏で1か月分のメニューを生成し、同じメニューが翌週に重複しないように配慮します。")

    with st.sidebar:
        render_sidebar_inputs()

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🍳 1週間分のメニューを生成", type="primary"):
            with st.spinner("1か月分のメニューを生成中..."):
                menu_data = generate_menu()
            if menu_data:
                st.session_state.menu_data = menu_data
                st.session_state.menu_view = build_menu_view(menu_data)
                st.session_state.show_menu = True
                st.success("メニューを生成しました！")
            else:
                st.error("メニュー生成に失敗しました。")
    with col2:
        if st.session_state.menu_data and st.button("🗑️ 生成結果をクリア"):
            st.session_state.menu_data = None
            st.session_state.menu_view = None
            st.session_state.show_menu = False
            st.rerun()

    if st.session_state.show_menu and st.session_state.menu_view:
        render_menu_results()


if __name__ == "__main__":
    main()
