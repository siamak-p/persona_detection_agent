
import streamlit as st
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from streamlit_ui.pages import chat_page, creator_page, passive_page, last_message_id_page, feedback_page, scheduler_page
from streamlit_ui.utils import get_api_url, check_unread_questions


st.set_page_config(
    page_title="PetaProcTwin API",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.sidebar.title("⚙️ تنظیمات")
api_url = st.sidebar.text_input(
    "URL API",
    value=get_api_url(),
    help="آدرس سرور API (به صورت پیش‌فرض: http://localhost:8000)",
)

st.session_state.api_url = api_url

current_user_id = st.sidebar.text_input(
    "🆔 شناسه کاربر",
    value=st.session_state.get("current_user_id", "user_1"),
    help="شناسه کاربر فعلی برای دریافت سوالات",
    key="current_user_input",
)
st.session_state.current_user_id = current_user_id

st.title("🚀 PetaProcTwin API Dashboard")
st.markdown("---")

has_unread, unread_count = check_unread_questions(api_url, current_user_id)

feedback_tab_title = "❓ سوالات و درخواست‌ها"
if has_unread:
    feedback_tab_title = f"❓ سوالات و درخواست‌ها ({unread_count}) 🔴"

tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "💬 Chat", 
    "✍️ Creator", 
    "📥 Passive", 
    "📋 Last Message ID",
    feedback_tab_title,
    "⏰ Scheduler",
])

with tab1:
    chat_page()

with tab2:
    creator_page()

with tab3:
    passive_page()

with tab4:
    last_message_id_page()

with tab5:
    feedback_page()

with tab6:
    scheduler_page()
