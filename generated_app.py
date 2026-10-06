import streamlit as st
import os
import json
import csv
import io
import datetime
from openai import OpenAI

# DeepSeek APIクライアントの初期化
def get_deepseek_client():
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        st.error("環境変数 DEEPSEEK_API_KEY が設定されていません。")
        return None
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

# デフォルト食材リスト
DEFAULT_INGREDIENTS = {
    "野菜": ["じゃがいも", "人参", "玉ねぎ", "キュウリ", "ブロッコリー", "トマト", "プチトマト", "ピーマン", "キャベツ", "ほうれん草", "レタス", "長ネギ", "白菜"],
    "肉類": ["牛肉ブロック", "牛肉スライス", "豚肉ブロック", "豚肉スライス", "鶏モモ肉", "鶏むね肉", "ハム", "ソーセージ", "塩鮭"],
    "その他": ["玉子", "豆腐", "乾燥ワカメ", "こんにゃく"],
    "調味料": ["醤油", "ソース", "味噌", "塩", "砂糖", "塩コショウ", "お酢", "みりん", "七味", "マヨネーズ", "ケチャップ", "チューブワサビ", "チューブ辛子", "チューブニンニク", "和風ドレッシング", "洋風ドレッシング", "オイスターソース", "鶏がらスープの素", "ほんだしの素"]
}

# デフォルトのユーザー情報
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

# セッション状態の初期化
def init_session_state():
    if "user_info" not in st.session_state:
        st.session_state.user_info = DEFAULT_USER_INFO.copy()
    else:
        # 既存セッションに不足キーがあれば補完
        for key, default_value in DEFAULT_USER_INFO.items():
            if key not in st.session_state.user_info:
                st.session_state.user_info[key] = default_value
    if "ingredients" not in st.session_state:
        st.session_state.ingredients = {k: v.copy() for k, v in DEFAULT_INGREDIENTS.items()}
    else:
        for category, default_items in DEFAULT_INGREDIENTS.items():
            if category not in st.session_state.ingredients:
                st.session_state.ingredients[category] = default_items.copy()
    if "menu_data" not in st.session_state:
        st.session_state.menu_data = None
    if "show_menu" not in st.session_state:
        st.session_state.show_menu = False

# ユーザー情報CSVの生成
def user_info_to_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["項目", "値"])
    for key, value in st.session_state.user_info.items():
        writer.writerow([key, value])
    for category, items in st.session_state.ingredients.items():
        writer.writerow([f"食材_{category}", ",".join(items)])
    return output.getvalue()

# CSVからユーザー情報を読み込み
def load_user_info_from_csv(uploaded_file):
    try:
        content = uploaded_file.getvalue().decode("utf-8-sig")
        reader = csv.reader(io.StringIO(content))
        rows = list(reader)
        if len(rows) < 2:
            return False
        for row in rows[1:]:
            if len(row) < 2:
                continue
            key, value = row[0], row[1]
            if key.startswith("食材_"):
                category = key.replace("食材_", "")
                if category in st.session_state.ingredients:
                    st.session_state.ingredients[category] = [x.strip() for x in value.split(",") if x.strip()]
            elif key in st.session_state.user_info:
                if key == "旬の野菜利用":
                    st.session_state.user_info[key] = value.lower() == "true"
                else:
                    st.session_state.user_info[key] = value
        return True
    except Exception as e:
        st.error(f"CSV読み込みエラー: {e}")
        return False

# メニュー生成プロンプトの構築
def build_prompt():
    info = st.session_state.user_info
    ingredients = st.session_state.ingredients
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

# DeepSeek APIでメニュー生成
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
        menu_data = json.loads(content)
        return menu_data
    except Exception as e:
        st.error(f"メニュー生成エラー: {e}")
        return None

# メニューをCSVに変換
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

# メインUI
def main():
    st.set_page_config(page_title="1週間夕食メニュー提案", layout="wide")
    init_session_state()
    st.title("🍽️ 共働き家庭のための夕食メニュー提案アプリ")
    st.markdown("家族情報を入力し、1週間分の夕食メニューを生成します。裏で1か月分のメニューを生成し、同じメニューが翌週に重複しないように配慮します。")

    with st.sidebar:
        st.header("📋 家族情報入力")
        st.session_state.user_info["家族構成"] = st.text_input("家族構成", value=st.session_state.user_info.get("家族構成", ""), placeholder="例: 夫婦+子供2人")
        st.session_state.user_info["子供の年齢"] = st.text_input("子供の年齢", value=st.session_state.user_info.get("子供の年齢", ""), placeholder="例: 5歳, 8歳")
        st.subheader("料理者の熟練度")
        skill_options = ["初心者", "中級者", "上級者"]
        current_wa = st.session_state.user_info.get("料理者の熟練度_和", "初心者")
        current_yo = st.session_state.user_info.get("料理者の熟練度_洋", "初心者")
        current_chu = st.session_state.user_info.get("料理者の熟練度_中", "初心者")
        st.session_state.user_info["料理者の熟練度_和"] = st.selectbox("和食", skill_options, index=skill_options.index(current_wa) if current_wa in skill_options else 0)
        st.session_state.user_info["料理者の熟練度_洋"] = st.selectbox("洋食", skill_options, index=skill_options.index(current_yo) if current_yo in skill_options else 0)
        st.session_state.user_info["料理者の熟練度_中"] = st.selectbox("中華", skill_options, index=skill_options.index(current_chu) if current_chu in skill_options else 0)
        st.session_state.user_info["家族の好み_食材"] = st.text_area("家族の好み（食材）", value=st.session_state.user_info.get("家族の好み_食材", ""), placeholder="例: 鶏肉好き、魚は苦手")
        st.session_state.user_info["家族の苦手な料理・食材"] = st.text_area("家族の苦手な料理・食材", value=st.session_state.user_info.get("家族の苦手な料理・食材", ""), placeholder="例: ピーマン、レバー、セロリ、辛い料理")
        st.session_state.user_info["アレルギー"] = st.text_area("アレルギーの有無", value=st.session_state.user_info.get("アレルギー", ""), placeholder="例: 卵アレルギー")
        st.session_state.user_info["家族の皆が好きな料理"] = st.text_area("家族の皆が好きな料理", value=st.session_state.user_info.get("家族の皆が好きな料理", ""), placeholder="例: カレー、ハンバーグ")
        st.session_state.user_info["旬の野菜利用"] = st.checkbox("旬の野菜を利用する", value=st.session_state.user_info.get("旬の野菜利用", True))

        st.header("🥕 利用可能な食材")
        for category in ["野菜", "肉類", "その他", "調味料"]:
            with st.expander(f"{category}（クリックで編集）"):
                current_items = st.session_state.ingredients.get(category, [])
                text = st.text_area(f"{category}（カンマ区切り）", value=",".join(current_items), key=f"ing_{category}")
                st.session_state.ingredients[category] = [x.strip() for x in text.split(",") if x.strip()]

        st.header("💾 ユーザ情報の保存・読み込み")
        csv_data = user_info_to_csv()
        st.download_button("ユーザ情報をCSVでダウンロード", data=csv_data.encode("utf-8-sig"), file_name="user_info.csv", mime="text/csv")
        uploaded_file = st.file_uploader("ユーザ情報CSVをアップロード", type=["csv"])
        if uploaded_file is not None:
            if load_user_info_from_csv(uploaded_file):
                st.success("ユーザ情報を読み込みました。")
                st.rerun()

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("🍳 1週間分のメニューを生成", type="primary"):
            with st.spinner("1か月分のメニューを生成中..."):
                menu_data = generate_menu()
                if menu_data:
                    st.session_state.menu_data = menu_data
                    st.session_state.show_menu = True
                    st.success("メニューを生成しました！")
                else:
                    st.error("メニュー生成に失敗しました。")
    with col2:
        if st.session_state.menu_data and st.button("🗑️ 生成結果をクリア"):
            st.session_state.menu_data = None
            st.session_state.show_menu = False
            st.rerun()

    if st.session_state.show_menu and st.session_state.menu_data:
        menu_data = st.session_state.menu_data
        st.header("📅 1週間分の夕食メニュー")
        if "weeks" in menu_data and len(menu_data["weeks"]) > 0:
            week1 = menu_data["weeks"][0]
            for day in week1.get("days", []):
                with st.expander(f"{day.get('day', '')}のメニュー", expanded=True):
                    col_a, col_b = st.columns(2)
                    with col_a:
                        main = day.get("main_dish", {})
                        st.subheader(f"主菜: {main.get('name', '')}")
                        st.write(f"カテゴリ: {main.get('category', '')} / 調理方法: {main.get('cooking_method', '')}")
                        st.write(f"食材: {', '.join(main.get('ingredients', []))}")
                        st.write(f"レシピ: {main.get('recipe', '')}")
                    with col_b:
                        side = day.get("side_dish", {})
                        st.subheader(f"副菜: {side.get('name', '')}")
                        st.write(f"カテゴリ: {side.get('category', '')} / 調理方法: {side.get('cooking_method', '')}")
                        st.write(f"食材: {', '.join(side.get('ingredients', []))}")
                        st.write(f"レシピ: {side.get('recipe', '')}")

        st.header("📥 CSVダウンロード")
        col_d1, col_d2 = st.columns(2)
        with col_d1:
            csv_1week = menu_to_csv(menu_data, weeks=1)
            st.download_button("1週間分のメニューをCSVでダウンロード", data=csv_1week.encode("utf-8-sig"), file_name="menu_1week.csv", mime="text/csv")
        with col_d2:
            csv_4weeks = menu_to_csv(menu_data, weeks=4)
            st.download_button("1か月分のメニューをCSVでダウンロード", data=csv_4weeks.encode("utf-8-sig"), file_name="menu_4weeks.csv", mime="text/csv")

if __name__ == "__main__":
    main()
