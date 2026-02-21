
import streamlit as st
import uuid
import time
import sys
import base64
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from streamlit_ui.utils import make_api_request, make_scheduler_request, get_current_timestamp, display_response

VOICE_BASE_URL = "http://localhost:8000"

def chat_page():
    st.header("💬 Chat Endpoint")
    st.markdown("ارسال پیام چت بین دو کاربر")

    if "creator_users" not in st.session_state:
        st.session_state.creator_users = []

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    if "chat_auto_msg_id" not in st.session_state:
        st.session_state.chat_auto_msg_id = str(uuid.uuid4())
    if "chat_auto_timestamp" not in st.session_state:
        st.session_state.chat_auto_timestamp = get_current_timestamp()

    col1, col2 = st.columns(2)

    with col1:
        user_id = st.text_input("User ID *", key="chat_user_id", value="user1")

        to_user_id = st.text_input(
            "To User ID *", 
            key="chat_to_user_id", 
            value="user2",
            help="شناسه کاربری که می‌خواهید با Twin او صحبت کنید",
        )
        
        available_users = [u for u in st.session_state.creator_users if u != user_id]
        if available_users:
            st.caption(f"💡 کاربران موجود: {', '.join(available_users)}")

        conversation_id = st.text_input("Conversation ID *", key="chat_conv_id", value="conv1")
        language = st.selectbox(
            "Language",
            options=[("fa", "فارسی"), ("en", "English")],
            format_func=lambda opt: f"{opt[0]} - {opt[1]}",
            key="chat_language",
            index=0,
            help="زبان پاسخ مدل؛ پیش‌فرض فارسی است.",
        )[0]

    with col2:
        st.text_input(
            "Message ID (خودکار)",
            key="chat_msg_id_display",
            value=st.session_state.chat_auto_msg_id,
            disabled=True,
            help="این شناسه به صورت خودکار تولید می‌شود",
        )
        message_id = st.session_state.chat_auto_msg_id
        st.text_input(
            "Timestamp * (خودکار)",
            key="chat_timestamp_display",
            value=st.session_state.chat_auto_timestamp,
            disabled=True,
            help="این زمان به صورت خودکار تولید می‌شود",
        )
        timestamp = st.session_state.chat_auto_timestamp

    st.markdown(
        """
    <script>
    function setupEnterKey() {
        const textArea = document.querySelector('textarea[data-testid*="chat_message_form"]');
        if (textArea) {
            textArea.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    const form = textArea.closest('form');
                    if (form) {
                        const submitButton = form.querySelector('button[type="submit"]');
                        if (submitButton) {
                            submitButton.click();
                        }
                    }
                }
            });
        }
    }
    setTimeout(setupEnterKey, 100);
    </script>
    """,
        unsafe_allow_html=True,
    )

    input_mode = st.radio(
        "نوع ورودی",
        options=["text", "voice"],
        format_func=lambda x: "📝 متن" if x == "text" else "🎤 صوت",
        horizontal=True,
        key="chat_input_mode_radio",
    )

    if input_mode == "text":
        with st.form("chat_form", clear_on_submit=True):
            message = st.text_area(
                "Message *",
                key="chat_message_form",
                height=100,
                help="برای ارسال، Ctrl+Enter (یا Cmd+Enter در Mac) را بزنید",
            )

            correlation_id = st.text_input(
                "Correlation ID (Optional)",
                key="chat_correlation_id_form",
                value="",
                help="شناسه همبستگی برای ردیابی (اختیاری)",
            )

            submitted = st.form_submit_button(
                "📤 ارسال درخواست Chat", type="primary", use_container_width=True
            )

            if submitted:
                if not message:
                    st.error("❌ لطفاً پیام را وارد کنید.")
                elif not all([user_id, to_user_id, conversation_id]):
                    st.error("❌ لطفاً تمام فیلدهای الزامی را پر کنید.")
                else:
                    st.session_state.chat_auto_msg_id = str(uuid.uuid4())
                    st.session_state.chat_auto_timestamp = get_current_timestamp()

                    request_data = {
                        "user_id": user_id,
                        "to_user_id": to_user_id,
                        "language": language,
                        "message": message,
                        "message_id": message_id,
                        "conversation_id": conversation_id,
                        "timestamp": timestamp,
                        "input_type": "text",
                    }

                    headers = {}
                    if correlation_id:
                        headers["X-Correlation-Id"] = correlation_id

                    with st.spinner("در حال ارسال درخواست..."):
                        response_data, error = make_api_request(
                            "POST", "/api/v1/chat", data=request_data, headers=headers
                        )

                    display_response(response_data, error)

                    if response_data and not error:
                        chat_entry = {
                            "user_message": message,
                            "agent_message": response_data.get("agent_message", ""),
                            "agent_timestamp": response_data.get("agent_timestamp", ""),
                            "agent_voice_url": response_data.get("agent_voice_url"),
                            "output_type": response_data.get("output_type", "text"),
                            "conversation_id": conversation_id,
                            "user_id": user_id,
                            "to_user_id": to_user_id,
                            "language": language,
                        }
                        st.session_state.chat_history.append(chat_entry)
                        if len(st.session_state.chat_history) > 50:
                            st.session_state.chat_history = st.session_state.chat_history[-50:]

                    st.rerun()

    else:
        st.markdown("### 🎤 ضبط صدا")
        st.info("روی دکمه ضبط کلیک کنید، صحبت کنید، سپس دوباره کلیک کنید تا ضبط متوقف شود.")
        
        try:
            from audio_recorder_streamlit import audio_recorder
            
            audio_bytes = audio_recorder(
                text="🎤 کلیک برای ضبط",
                recording_color="#e74c3c",
                neutral_color="#3498db",
                icon_name="microphone",
                icon_size="3x",
                pause_threshold=2.0,
                sample_rate=16000,
            )
            
            if audio_bytes:
                st.audio(audio_bytes, format="audio/wav")
                st.success("✅ ضبط انجام شد!")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("📤 ارسال", type="primary", use_container_width=True, key="send_voice"):
                        if not all([user_id, to_user_id, conversation_id]):
                            st.error("❌ لطفاً تمام فیلدهای الزامی را پر کنید.")
                        else:
                            st.session_state.chat_auto_msg_id = str(uuid.uuid4())
                            st.session_state.chat_auto_timestamp = get_current_timestamp()
                            
                            voice_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                            
                            request_data = {
                                "user_id": user_id,
                                "to_user_id": to_user_id,
                                "language": language,
                                "message": "",
                                "message_id": message_id,
                                "conversation_id": conversation_id,
                                "timestamp": timestamp,
                                "input_type": "voice",
                                "voice_data": voice_b64,
                                "voice_format": "wav",
                            }
                            
                            with st.spinner("در حال ارسال و پردازش صدا..."):
                                response_data, error = make_api_request(
                                    "POST", "/api/v1/chat", data=request_data
                                )
                            
                            display_response(response_data, error)
                            
                            if response_data and not error:
                                chat_entry = {
                                    "user_message": "[پیام صوتی]",
                                    "agent_message": response_data.get("agent_message", ""),
                                    "agent_timestamp": response_data.get("agent_timestamp", ""),
                                    "agent_voice_url": response_data.get("agent_voice_url"),
                                    "output_type": response_data.get("output_type", "text"),
                                    "conversation_id": conversation_id,
                                    "user_id": user_id,
                                    "to_user_id": to_user_id,
                                    "language": language,
                                }
                                st.session_state.chat_history.append(chat_entry)
                                if len(st.session_state.chat_history) > 50:
                                    st.session_state.chat_history = st.session_state.chat_history[-50:]
                            
                            st.rerun()
                
                with col2:
                    if st.button("🗑️ لغو", type="secondary", use_container_width=True, key="cancel_voice"):
                        st.rerun()
                        
        except ImportError:
            st.error("""
            ❌ کتابخانه audio-recorder-streamlit نصب نیست.
            
            لطفاً نصب کنید:
            ```
            pip install audio-recorder-streamlit
            ```
            """)
            
            st.markdown("**یا فایل صوتی آپلود کنید:**")
            voice_file = st.file_uploader(
                "فایل صوتی",
                type=["mp3", "wav", "webm", "ogg", "m4a"],
                key="chat_voice_file_fallback",
            )
            if voice_file:
                if st.button("📤 ارسال فایل", type="primary", key="send_fallback_voice"):
                    if not all([user_id, to_user_id, conversation_id]):
                        st.error("❌ لطفاً تمام فیلدهای الزامی را پر کنید.")
                    else:
                        st.session_state.chat_auto_msg_id = str(uuid.uuid4())
                        st.session_state.chat_auto_timestamp = get_current_timestamp()
                        
                        voice_bytes = voice_file.read()
                        voice_b64 = base64.b64encode(voice_bytes).decode('utf-8')
                        
                        request_data = {
                            "user_id": user_id,
                            "to_user_id": to_user_id,
                            "language": language,
                            "message": "",
                            "message_id": message_id,
                            "conversation_id": conversation_id,
                            "timestamp": timestamp,
                            "input_type": "voice",
                            "voice_data": voice_b64,
                            "voice_format": voice_file.name.split('.')[-1],
                        }
                        
                        with st.spinner("در حال ارسال..."):
                            response_data, error = make_api_request(
                                "POST", "/api/v1/chat", data=request_data
                            )
                        
                        display_response(response_data, error)
                        
                        if response_data and not error:
                            chat_entry = {
                                "user_message": "[پیام صوتی]",
                                "agent_message": response_data.get("agent_message", ""),
                                "agent_timestamp": response_data.get("agent_timestamp", ""),
                                "agent_voice_url": response_data.get("agent_voice_url"),
                                "output_type": response_data.get("output_type", "text"),
                                "conversation_id": conversation_id,
                                "user_id": user_id,
                                "to_user_id": to_user_id,
                                "language": language,
                            }
                            st.session_state.chat_history.append(chat_entry)
                            if len(st.session_state.chat_history) > 50:
                                st.session_state.chat_history = st.session_state.chat_history[-50:]
                        
                        st.rerun()

    if st.session_state.chat_history:
        st.markdown("---")
        st.subheader("📜 تاریخچه مکالمات")

        current_conv_id = st.session_state.get("chat_conv_id", "conv1")

        filtered_history = [
            msg
            for msg in st.session_state.chat_history
            if msg.get("conversation_id") == current_conv_id
        ]

        if filtered_history:
            for idx, entry in enumerate(reversed(filtered_history[-10:])):
                with st.container():
                    st.markdown(
                        f"""
                    <div style='background-color: #E8F4F8; color: #2C3E50; padding: 14px; border-radius: 10px; margin-bottom: 12px; border-left: 4px solid #5DADE2; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
                        <strong style='color: #34495E;'>👤 شما ({entry.get('user_id', 'N/A')}):</strong><br>
                        <div style='margin-top: 8px; color: #2C3E50; line-height: 1.6;'>{entry.get('user_message', '')}</div>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

                    if entry.get("agent_message"):
                        st.markdown(
                            f"""
                        <div style='background-color: #F0F9F4; color: #2C3E50; padding: 14px; border-radius: 10px; margin-bottom: 20px; border-left: 4px solid #58D68D; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
                            <strong style='color: #27AE60;'>🤖 AI ({entry.get('to_user_id', 'N/A')}):</strong><br>
                            <div style='margin-top: 8px; color: #2C3E50; line-height: 1.6;'>{entry.get('agent_message', '')}</div>
                            <div style='margin-top: 10px; font-size: 0.85em; color: #7F8C8D;'>⏰ {entry.get('agent_timestamp', '')}</div>
                        </div>
                        """,
                            unsafe_allow_html=True,
                        )
                        
                        voice_url = entry.get("agent_voice_url")
                        if voice_url:
                            full_url = f"{VOICE_BASE_URL}{voice_url}"
                            st.audio(full_url, format="audio/mpeg")

                    st.markdown("---")

        if st.button("🗑️ پاک کردن تاریخچه", key="clear_chat_history"):
            st.session_state.chat_history = []
            st.rerun()


def creator_page():
    st.header("✍️ Creator Endpoint")
    st.markdown("ارسال پیام به Creator Agent")

    if "creator_users" not in st.session_state:
        st.session_state.creator_users = []

    if "creator_responses" not in st.session_state:
        st.session_state.creator_responses = []

    if "creator_auto_msg_id" not in st.session_state:
        st.session_state.creator_auto_msg_id = str(uuid.uuid4())
    if "creator_auto_timestamp" not in st.session_state:
        st.session_state.creator_auto_timestamp = get_current_timestamp()

    col1, col2 = st.columns(2)

    with col1:
        user_id = st.text_input("User ID *", key="creator_user_id", value="user1")
        st.text_input(
            "Message ID (خودکار)",
            key="creator_msg_id_display",
            value=st.session_state.creator_auto_msg_id,
            disabled=True,
            help="این شناسه به صورت خودکار تولید می‌شود",
        )
        message_id = st.session_state.creator_auto_msg_id

    with col2:
        language = st.selectbox(
            "Language",
            options=[("fa", "فارسی"), ("en", "English")],
            format_func=lambda opt: f"{opt[0]} - {opt[1]}",
            key="creator_language",
            index=0,
            help="زبان پاسخ مدل؛ پیش‌فرض فارسی است.",
        )[0]
        st.text_input(
            "Timestamp * (خودکار)",
            key="creator_timestamp_display",
            value=st.session_state.creator_auto_timestamp,
            disabled=True,
            help="این زمان به صورت خودکار تولید می‌شود",
        )
        timestamp = st.session_state.creator_auto_timestamp

    st.markdown(
        """
    <script>
    function setupCreatorEnterKey() {
        const textArea = document.querySelector('textarea[data-testid*="creator_message_form"]');
        if (textArea) {
            textArea.addEventListener('keydown', function(e) {
                if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                    e.preventDefault();
                    const form = textArea.closest('form');
                    if (form) {
                        const submitButton = form.querySelector('button[type="submit"]');
                        if (submitButton) {
                            submitButton.click();
                        }
                    }
                }
            });
        }
    }
    setTimeout(setupCreatorEnterKey, 100);
    </script>
    """,
        unsafe_allow_html=True,
    )

    input_mode = st.radio(
        "نوع ورودی",
        options=["text", "voice"],
        format_func=lambda x: "📝 متن" if x == "text" else "🎤 صوت",
        horizontal=True,
        key="creator_input_mode_radio",
    )

    if input_mode == "text":
        with st.form("creator_form", clear_on_submit=True):
            message = st.text_area(
                "Message *",
                key="creator_message_form",
                height=100,
                help="برای ارسال، Ctrl+Enter (یا Cmd+Enter در Mac) را بزنید",
            )

            correlation_id = st.text_input(
                "Correlation ID (Optional)",
                key="creator_correlation_id_form",
                value="",
                help="شناسه همبستگی برای ردیابی (اختیاری)",
            )

            submitted = st.form_submit_button(
                "📤 ارسال درخواست Creator", type="primary", use_container_width=True
            )

            if submitted:
                if not all([user_id, message]):
                    st.error("❌ لطفاً تمام فیلدهای الزامی را پر کنید.")
                else:
                    st.session_state.creator_auto_msg_id = str(uuid.uuid4())
                    st.session_state.creator_auto_timestamp = get_current_timestamp()

                    request_data = {
                        "user_id": user_id,
                        "language": language,
                        "message": message,
                        "message_id": message_id,
                        "timestamp": timestamp,
                        "input_type": "text",
                    }

                    headers = {}
                    if correlation_id:
                        headers["X-Correlation-Id"] = correlation_id

                    with st.spinner("در حال ارسال درخواست..."):
                        response_data, error = make_api_request(
                            "POST", "/api/v1/creator", data=request_data, headers=headers
                        )

                    display_response(response_data, error)

                    if user_id and user_id not in st.session_state.creator_users:
                        st.session_state.creator_users.append(user_id)

                    if response_data and not error:
                        creator_entry = {
                            "user_id": user_id,
                            "language": language,
                            "user_message": message,
                            "agent_message": response_data.get("agent_message", ""),
                            "agent_timestamp": response_data.get("agent_timestamp", ""),
                            "agent_voice_url": response_data.get("agent_voice_url"),
                        }
                        st.session_state.creator_responses.append(creator_entry)
                        if len(st.session_state.creator_responses) > 20:
                            st.session_state.creator_responses = st.session_state.creator_responses[-20:]

                    st.rerun()

    else:
        st.markdown("### 🎤 ضبط صدا")
        st.info("روی دکمه ضبط کلیک کنید، صحبت کنید، سپس دوباره کلیک کنید تا ضبط متوقف شود.")
        
        try:
            from audio_recorder_streamlit import audio_recorder
            
            audio_bytes = audio_recorder(
                text="🎤 کلیک برای ضبط",
                recording_color="#e74c3c",
                neutral_color="#9b59b6",
                icon_name="microphone",
                icon_size="3x",
                pause_threshold=2.0,
                sample_rate=16000,
            )
            
            if audio_bytes:
                st.audio(audio_bytes, format="audio/wav")
                st.success("✅ ضبط انجام شد!")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("📤 ارسال", type="primary", use_container_width=True, key="creator_send_voice"):
                        if not user_id:
                            st.error("❌ لطفاً User ID را وارد کنید.")
                        else:
                            st.session_state.creator_auto_msg_id = str(uuid.uuid4())
                            st.session_state.creator_auto_timestamp = get_current_timestamp()
                            
                            voice_b64 = base64.b64encode(audio_bytes).decode('utf-8')
                            
                            request_data = {
                                "user_id": user_id,
                                "language": language,
                                "message": "",
                                "message_id": message_id,
                                "timestamp": timestamp,
                                "input_type": "voice",
                                "voice_data": voice_b64,
                                "voice_format": "wav",
                            }
                            
                            with st.spinner("در حال ارسال و پردازش صدا..."):
                                response_data, error = make_api_request(
                                    "POST", "/api/v1/creator", data=request_data
                                )
                            
                            display_response(response_data, error)
                            
                            if user_id and user_id not in st.session_state.creator_users:
                                st.session_state.creator_users.append(user_id)
                            
                            if response_data and not error:
                                creator_entry = {
                                    "user_id": user_id,
                                    "language": language,
                                    "user_message": "[پیام صوتی]",
                                    "agent_message": response_data.get("agent_message", ""),
                                    "agent_timestamp": response_data.get("agent_timestamp", ""),
                                    "agent_voice_url": response_data.get("agent_voice_url"),
                                }
                                st.session_state.creator_responses.append(creator_entry)
                                if len(st.session_state.creator_responses) > 20:
                                    st.session_state.creator_responses = st.session_state.creator_responses[-20:]
                            
                            st.rerun()
                
                with col2:
                    if st.button("🗑️ لغو", type="secondary", use_container_width=True, key="creator_cancel_voice"):
                        st.rerun()
                        
        except ImportError:
            st.error("""
            ❌ کتابخانه audio-recorder-streamlit نصب نیست.
            
            لطفاً نصب کنید:
            ```
            pip install audio-recorder-streamlit
            ```
            """)

    if st.session_state.creator_responses:
        st.markdown("---")
        st.subheader("📜 پاسخ‌های Creator")

        current_user_id = st.session_state.get("creator_user_id", "user1")

        user_responses = [
            resp
            for resp in st.session_state.creator_responses
            if resp.get("user_id") == current_user_id
        ]

        if user_responses:
            for idx, entry in enumerate(reversed(user_responses[-5:])):
                with st.container():
                    st.markdown(
                        f"""
                    <div style='background-color: #E8F4F8; color: #2C3E50; padding: 14px; border-radius: 10px; margin-bottom: 12px; border-left: 4px solid #5DADE2; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
                        <strong style='color: #34495E;'>👤 شما ({entry.get('user_id', 'N/A')}):</strong><br>
                        <div style='margin-top: 8px; color: #2C3E50; line-height: 1.6;'>{entry.get('user_message', '')}</div>
                    </div>
                    """,
                        unsafe_allow_html=True,
                    )

                    if entry.get("agent_message"):
                        st.markdown(
                            f"""
                        <div style='background-color: #FFF8F0; color: #2C3E50; padding: 14px; border-radius: 10px; margin-bottom: 20px; border-left: 4px solid #F8C471; box-shadow: 0 2px 4px rgba(0,0,0,0.05);'>
                            <strong style='color: #D68910;'>🤖 Creator AI:</strong><br>
                            <div style='margin-top: 8px; color: #2C3E50; line-height: 1.6;'>{entry.get('agent_message', '')}</div>
                            <div style='margin-top: 10px; font-size: 0.85em; color: #7F8C8D;'>⏰ {entry.get('agent_timestamp', '')}</div>
                        </div>
                        """,
                            unsafe_allow_html=True,
                        )

                    st.markdown("---")

        if st.button("🗑️ پاک کردن پاسخ‌ها", key="clear_creator_responses"):
            st.session_state.creator_responses = []
            st.rerun()

    if st.session_state.creator_users:
        with st.expander("👥 کاربران ایجاد شده در Creator"):
            for user in st.session_state.creator_users:
                st.text(f"• {user}")


def passive_page():
    st.header("📥 Passive Endpoint")
    st.markdown("ارسال رکوردهای Passive (مشاهدات)")

    num_items = st.number_input(
        "تعداد آیتم‌ها",
        min_value=1,
        max_value=10,
        value=1,
        key="passive_num_items",
    )

    for i in range(num_items):
        if f"passive_auto_msg_id_{i}" not in st.session_state:
            st.session_state[f"passive_auto_msg_id_{i}"] = str(uuid.uuid4())
        if f"passive_auto_timestamp_{i}" not in st.session_state:
            st.session_state[f"passive_auto_timestamp_{i}"] = get_current_timestamp()

    items = []
    for i in range(num_items):
        st.markdown(f"### آیتم {i + 1}")
        col1, col2 = st.columns(2)

        with col1:
            user_id = st.text_input(
                f"User ID *",
                key=f"passive_user_id_{i}",
                value="user1",
            )
            to_user_id = st.text_input(
                f"To User ID *",
                key=f"passive_to_user_id_{i}",
                value="user2",
            )
            conversation_id = st.text_input(
                f"Conversation ID *",
                key=f"passive_conv_id_{i}",
                value="conv1",
            )

        with col2:
            st.text_input(
                f"Message ID (خودکار)",
                key=f"passive_msg_id_display_{i}",
                value=st.session_state[f"passive_auto_msg_id_{i}"],
                disabled=True,
                help="این شناسه به صورت خودکار تولید می‌شود",
            )
            message_id = st.session_state[f"passive_auto_msg_id_{i}"]
            st.text_input(
                f"Timestamp * (خودکار)",
                key=f"passive_timestamp_display_{i}",
                value=st.session_state[f"passive_auto_timestamp_{i}"],
                disabled=True,
                help="این زمان به صورت خودکار تولید می‌شود",
            )
            timestamp = st.session_state[f"passive_auto_timestamp_{i}"]

        message = st.text_area(
            f"Message *",
            key=f"passive_message_{i}",
            height=80,
        )

        if i < num_items - 1:
            st.markdown("---")

        items.append(
            {
                "user_id": user_id,
                "to_user_id": to_user_id,
                "conversation_id": conversation_id,
                "message": message,
                "message_id": message_id,
                "timestamp": timestamp,
            }
        )

    correlation_id = st.text_input(
        "Correlation ID (Optional)",
        key="passive_correlation_id",
        value="",
        help="شناسه همبستگی برای ردیابی (اختیاری)",
    )

    if st.button("📤 ارسال درخواست Passive", type="primary", use_container_width=True):
        all_valid = True
        for item in items:
            if not all(
                [
                    item["user_id"],
                    item["to_user_id"],
                    item["conversation_id"],
                    item["message"],
                ]
            ):
                all_valid = False
                break

        if not all_valid:
            st.error("❌ لطفاً تمام فیلدهای الزامی را برای همه آیتم‌ها پر کنید.")
            return

        for i in range(num_items):
            st.session_state[f"passive_auto_msg_id_{i}"] = str(uuid.uuid4())
            st.session_state[f"passive_auto_timestamp_{i}"] = get_current_timestamp()

        headers = {}
        if correlation_id:
            headers["X-Correlation-Id"] = correlation_id

        with st.spinner("در حال ارسال درخواست..."):
            response_data, error = make_api_request(
                "POST", "/api/v1/passive", data=items, headers=headers
            )

        display_response(response_data, error)

        if response_data or error:
            st.rerun()


def last_message_id_page():
    st.header("📋 Last Message ID Endpoint")
    st.markdown("دریافت آخرین Message ID از Passive Service")

    if st.button("📥 دریافت Last Message ID", type="primary", use_container_width=True):
        with st.spinner("در حال دریافت اطلاعات..."):
            response_data, error = make_api_request("GET", "/api/v1/passive/last-msgId")

        display_response(response_data, error)

        if response_data and "lastMsgId" in response_data:
            st.info(f"📌 Last Message ID: `{response_data['lastMsgId']}`")


def scheduler_page():
    st.header("⏰ مدیریت Scheduler ها")
    st.markdown("""
    در این بخش می‌توانید Scheduler های سیستم را به صورت دستی اجرا کنید.
    
    ⚠️ **توجه:** این عملیات‌ها معمولاً به صورت خودکار در پس‌زمینه اجرا می‌شوند.
    """)
    
    st.subheader("📊 وضعیت کلی Scheduler ها")
    
    if st.button("🔄 بارگذاری وضعیت", key="refresh_scheduler_status"):
        st.rerun()
    
    with st.spinner("در حال دریافت وضعیت..."):
        status_response, status_error = make_api_request(
            "GET", "/api/v1/admin/scheduler/status"
        )
    
    if status_error:
        st.error(f"❌ خطا در دریافت وضعیت: {status_error}")
    elif status_response:
        enabled_status = "✅ فعال" if status_response.get('scheduler_enabled') else "❌ غیرفعال"
        st.info(f"**وضعیت کلی Scheduler ها:** {enabled_status}")
    
    st.markdown("---")
    
    st.subheader("📝 خلاصه‌سازی (Summarization)")
    
    tab_chat, tab_passive = st.tabs(["💬 Chat Summary", "📋 Passive Summary"])
    
    with tab_chat:
        st.markdown("#### 💬 خلاصه‌سازی چت")
        st.caption("خلاصه‌سازی یک مکالمه چت خاص با استخراج Core Facts")
        
        col1, col2 = st.columns(2)
        with col1:
            chat_user_id = st.text_input("User ID", key="chat_summ_user_id", value="user1")
            chat_to_user_id = st.text_input("To User ID", key="chat_summ_to_user_id", value="user2")
        with col2:
            chat_conversation_id = st.text_input("Conversation ID", key="chat_summ_conv_id", value="conv1")
        
        if st.button("▶️ اجرای خلاصه‌سازی چت", key="run_chat_summary", type="primary"):
            start_time = time.time()
            with st.spinner("در حال خلاصه‌سازی چت..."):
                response, error = make_scheduler_request(
                    "POST", "/api/v1/admin/scheduler/chat-summary/run",
                    json={
                        "user_id": chat_user_id,
                        "to_user_id": chat_to_user_id,
                        "conversation_id": chat_conversation_id,
                    }
                )
            elapsed = time.time() - start_time
            if error:
                st.error(f"❌ خطا: {error}")
            else:
                st.success(f"✅ {response.get('message', 'اجرا شد')}")
                st.caption(f"⏱️ زمان اجرا: {elapsed:.1f} ثانیه")
        
        st.markdown("---")
        
        st.markdown("##### 🔄 Chat Summary Retry Worker")
        st.caption("پردازش مجدد خلاصه‌سازی‌های ناموفق چت")
        
        col1, col2 = st.columns([1, 2])
        with col1:
            if st.button("▶️ اجرا", key="run_chat_retry_worker", type="primary"):
                start_time = time.time()
                with st.spinner("در حال اجرای Retry Worker..."):
                    response, error = make_scheduler_request(
                        "POST", "/api/v1/admin/scheduler/retry/run"
                    )
                elapsed = time.time() - start_time
                if error:
                    st.error(f"❌ خطا: {error}")
                else:
                    st.success(f"✅ {response.get('message', 'اجرا شد')}")
                    st.caption(f"⏱️ زمان: {elapsed:.1f} ثانیه")
        
        with col2:
            with st.spinner("در حال دریافت آمار..."):
                summary_stats_response, summary_stats_error = make_api_request(
                    "GET", "/api/v1/admin/scheduler/retry/stats"
                )
            if summary_stats_response:
                c1, c2, c3 = st.columns(3)
                with c1:
                    st.metric("کل", summary_stats_response.get('retry_total', 0))
                with c2:
                    st.metric("آماده", summary_stats_response.get('retry_pending', 0))
                with c3:
                    st.metric("❌ شکست", summary_stats_response.get('failed_total', 0))
    
    with tab_passive:
        st.markdown("#### 📋 خلاصه‌سازی Passive")
        st.caption("خلاصه‌سازی پیام‌های passive آرشیو شده")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ اجرای Passive Summarization", key="run_passive_summarization", type="primary", use_container_width=True):
                start_time = time.time()
                with st.spinner("در حال اجرای Passive Summarization... (ممکن است چند دقیقه طول بکشد)"):
                    response, error = make_scheduler_request(
                        "POST", "/api/v1/admin/scheduler/passive-summarization/run"
                    )
                elapsed = time.time() - start_time
                if error:
                    st.error(f"❌ خطا: {error}")
                else:
                    st.success(f"✅ {response.get('message', 'اجرا شد')}")
                    st.caption(f"⏱️ زمان اجرا: {elapsed:.1f} ثانیه")
                    stats = response.get('stats', {})
                    if stats:
                        st.json(stats)
        
        with col2:
            if st.button("▶️ اجرای Passive Retry Worker", key="run_passive_summarization_retry", type="primary", use_container_width=True):
                start_time = time.time()
                with st.spinner("در حال اجرای Passive Summarization Retry Worker..."):
                    response, error = make_scheduler_request(
                        "POST", "/api/v1/admin/scheduler/passive-summarization-retry/run"
                    )
                elapsed = time.time() - start_time
                if error:
                    st.error(f"❌ خطا: {error}")
                else:
                    st.success(f"✅ {response.get('message', 'اجرا شد')}")
                    st.caption(f"⏱️ زمان: {elapsed:.1f} ثانیه")
        
        st.markdown("##### 📈 آمار صف Passive Summarization")
        with st.spinner("در حال دریافت آمار..."):
            passive_stats_response, passive_stats_error = make_api_request(
                "GET", "/api/v1/admin/scheduler/passive-summarization/stats"
            )
        if passive_stats_response:
            c1, c2, c3 = st.columns(3)
            with c1:
                st.metric("کل", passive_stats_response.get('retry_total', 0))
            with c2:
                st.metric("آماده", passive_stats_response.get('retry_pending', 0))
            with c3:
                st.metric("❌ شکست", passive_stats_response.get('failed_total', 0))
    
    st.markdown("---")
    
    st.subheader("🎵 تحلیل لحن و شخصیت (Tone Analysis)")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🎵 Tone Scheduler")
        st.caption("تشخیص لحن و شخصیت کاربران از پیام‌های passive")
        if st.button("▶️ اجرا", key="run_tone_scheduler", type="primary", use_container_width=True):
            start_time = time.time()
            with st.spinner("در حال اجرای Tone Scheduler... (ممکن است چند دقیقه طول بکشد)"):
                response, error = make_scheduler_request(
                    "POST", "/api/v1/admin/scheduler/tone/run"
                )
            elapsed = time.time() - start_time
            if error:
                st.error(f"❌ خطا: {error}")
            else:
                st.success(f"✅ {response.get('message', 'اجرا شد')}")
                st.caption(f"⏱️ زمان اجرا: {elapsed:.1f} ثانیه")
                stats = response.get('stats', {})
                if stats:
                    st.json(stats)
    
    with col2:
        st.markdown("#### 🔄 Tone Retry Worker")
        st.caption("پردازش مجدد تحلیل‌های ناموفق لحن")
        if st.button("▶️ اجرا", key="run_tone_retry_worker", type="primary", use_container_width=True):
            start_time = time.time()
            with st.spinner("در حال اجرای Tone Retry Worker..."):
                response, error = make_scheduler_request(
                    "POST", "/api/v1/admin/scheduler/tone-retry/run"
                )
            elapsed = time.time() - start_time
            if error:
                st.error(f"❌ خطا: {error}")
            else:
                st.success(f"✅ {response.get('message', 'اجرا شد')}")
                st.caption(f"⏱️ زمان: {elapsed:.1f} ثانیه")
    
    st.markdown("##### 📈 آمار صف Tone Analysis")
    with st.spinner("در حال دریافت آمار..."):
        tone_stats_response, tone_stats_error = make_api_request(
            "GET", "/api/v1/admin/scheduler/tone-retry/stats"
        )
    if tone_stats_response:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("کل", tone_stats_response.get('retry_total', 0))
        with c2:
            st.metric("آماده", tone_stats_response.get('retry_pending', 0))
        with c3:
            st.metric("❌ شکست", tone_stats_response.get('failed_total', 0))
    
    st.markdown("---")
    
    st.subheader("❓ سوالات رابطه (Feedback)")
    
    st.markdown("#### ❓ Feedback Scheduler")
    st.caption("تولید سوالات رابطه برای کاربران با روابط stranger")
    
    if st.button("▶️ اجرای Feedback Scheduler", key="run_feedback_scheduler", type="primary"):
        start_time = time.time()
        with st.spinner("در حال اجرای Feedback Scheduler..."):
            response, error = make_scheduler_request(
                "POST", "/api/v1/admin/scheduler/feedback/run"
            )
        elapsed = time.time() - start_time
        if error:
            st.error(f"❌ خطا: {error}")
        else:
            st.success(f"✅ {response.get('message', 'اجرا شد')}")
            st.caption(f"⏱️ زمان اجرا: {elapsed:.1f} ثانیه")
            stats = response.get('stats', {})
            if stats:
                st.json(stats)
    
    st.markdown("---")
    st.caption("💡 این scheduler ها به صورت خودکار در فواصل زمانی مشخص اجرا می‌شوند.")


def feedback_page():
    st.header("❓ سوالات و درخواست‌ها")
    st.markdown("""
    در این بخش، سوالاتی از شما درباره روابطتان پرسیده می‌شود و همچنین درخواست‌های برنامه‌ریزی آینده که دیگران از شما داشته‌اند نمایش داده می‌شود.
    
    🔒 **حریم خصوصی:** پاسخ‌های شما فقط برای بهبود تجربه چت استفاده می‌شوند.
    """)
    
    current_user_id = st.session_state.get("current_user_id", "user_1")
    
    with st.spinner("در حال دریافت..."):
        response_data, error = make_api_request(
            "GET", f"/api/v1/feedback/questions/{current_user_id}"
        )
    
    if error:
        st.error(error)
        return
    
    if not response_data:
        st.info("✅ هیچ سوال یا درخواستی برای شما وجود ندارد!")
        return
    
    questions = response_data.get("questions", [])
    future_requests = response_data.get("future_requests", [])
    
    financial_threads = []
    fin_threads_response, fin_threads_error = make_api_request(
        "GET", f"/api/v1/feedback/financial-threads/{current_user_id}"
    )
    if fin_threads_response:
        financial_threads = fin_threads_response.get("threads", [])
    
    if not questions and not future_requests and not financial_threads:
        st.success("✅ همه سوالات و درخواست‌ها پاسخ داده شده‌اند! 🎉")
        return
    
    total = len(questions) + len(future_requests) + len(financial_threads)
    st.info(f"📬 شما {total} مورد پاسخ نداده دارید ({len(questions)} سوال رابطه، {len(future_requests)} درخواست برنامه‌ریزی، {len(financial_threads)} موضوع مالی)")
    
    if future_requests:
        st.markdown("---")
        st.subheader("📅 درخواست‌های برنامه‌ریزی آینده")
        st.caption("این درخواست‌ها از طرف دوستانتان آمده و منتظر پاسخ شما هستند.")
        
        for idx, req in enumerate(future_requests):
            sender_display = req.get('sender_name') or req['sender_id']
            rel_label = req.get('relationship_label')
            expander_title = f"📅 درخواست از: {sender_display}"
            if rel_label:
                expander_title += f" ({rel_label})"
            expander_title += f" - {req['detected_plan']}"
            
            with st.expander(expander_title, expanded=(idx == 0)):
                sender_info_parts = []
                if req.get('sender_name'):
                    sender_info_parts.append(f"**{req['sender_name']}**")
                else:
                    sender_info_parts.append(f"کاربر {req['sender_id']}")
                
                if rel_label:
                    sender_info_parts.append(f"({rel_label} شما)")
                
                time_info = req.get('created_at_formatted') or req.get('created_at', '')
                
                st.markdown(f"""
                <div style='background-color: #3D5A80; color: #FFFFFF; padding: 12px; border-radius: 8px; margin-bottom: 15px;'>
                    <strong style='color: #98C1D9;'>👤 فرستنده:</strong> {' '.join(sender_info_parts)}<br>
                    <strong style='color: #98C1D9;'>🕐 زمان درخواست:</strong> {time_info}
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div style='background-color: #2E4A62; color: #FFFFFF; padding: 15px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #FF9800;'>
                    <strong style='color: #FFD700;'>💬 پیام اصلی:</strong><br><br>
                    <div style='white-space: pre-wrap; color: #E0E0E0; font-size: 1.1em;'>{req['original_message']}</div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div style='background-color: #1E3A5F; color: #FFFFFF; padding: 10px; border-radius: 8px; margin-bottom: 15px;'>
                    <strong>📋 برنامه تشخیص داده شده:</strong> {req['detected_plan']}<br>
                    <strong>⏰ زمان پیشنهادی:</strong> {req.get('detected_datetime') or 'مشخص نشده'}
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("### 📝 پاسخ شما:")
                
                response_text = st.text_area(
                    "پاسخ خود را بنویسید:",
                    key=f"future_response_{req['id']}",
                    height=100,
                    placeholder="مثلاً: باشه، ساعت ۵ خوبه؟ یا: امروز نمیتونم، فردا چطوره؟",
                )
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button(
                        "✅ ارسال پاسخ",
                        key=f"submit_future_{req['id']}",
                        type="primary",
                        disabled=not response_text.strip(),
                    ):
                        with st.spinner("در حال ارسال پاسخ..."):
                            submit_response, submit_error = make_api_request(
                                "POST",
                                "/api/v1/feedback/future-requests/respond",
                                data={
                                    "request_id": req['id'],
                                    "response_text": response_text.strip(),
                                },
                            )
                        
                        if submit_error:
                            st.error(submit_error)
                        else:
                            st.success("✅ پاسخ شما ارسال شد! در پیام بعدی به فرستنده اطلاع داده می‌شود.")
                            st.balloons()
                            time.sleep(1)
                            st.rerun()
                
                with col2:
                    if st.button(
                        "❌ رد کردن",
                        key=f"reject_future_{req['id']}",
                        help="این درخواست را رد کن",
                    ):
                        with st.spinner("در حال ثبت..."):
                            reject_response, reject_error = make_api_request(
                                "POST",
                                "/api/v1/feedback/future-requests/respond",
                                data={
                                    "request_id": req['id'],
                                    "response_text": "متأسفانه امکانش نیست.",
                                },
                            )
                        
                        if reject_error:
                            st.error(reject_error)
                        else:
                            st.info("رد شد")
                            st.rerun()
                
                st.caption(f"📅 تاریخ درخواست: {req.get('created_at', 'N/A')}")
    
    if financial_threads:
        waiting_threads = [t for t in financial_threads if t.get('waiting_for') == 'creator']
        waiting_count = len(waiting_threads)
        
        st.markdown("---")
        if waiting_count > 0:
            st.subheader(f"💰 موضوعات مالی ({waiting_count})")
        else:
            st.subheader("💰 موضوعات مالی")
        st.caption("این موضوعات مالی منتظر پاسخ شما هستند.")
        
        for idx, thread in enumerate(waiting_threads):
            sender_name = thread.get('sender_name') or thread['sender_id']
            relationship = thread.get('relationship_type')
            
            if relationship:
                sender_display = f"{sender_name} ({relationship})"
            else:
                sender_display = sender_name
            
            expander_title = f"💰 {sender_display} - {thread['topic_summary'][:50]}..."
            
            with st.expander(expander_title, expanded=(idx == 0)):
                relationship_html = f"<br><strong style='color: #98C1D9;'>🔗 رابطه:</strong> {relationship}" if relationship else ""
                st.markdown(f"""
                <div style='background-color: #3D5A80; color: #FFFFFF; padding: 12px; border-radius: 8px; margin-bottom: 15px;'>
                    <strong style='color: #98C1D9;'>👤 فرستنده:</strong> {sender_name}{relationship_html}<br>
                    <strong style='color: #98C1D9;'>🕐 زمان درخواست:</strong> {thread.get('created_at', 'N/A')}
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div style='background-color: #2E4A62; color: #FFFFFF; padding: 15px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #FF9800;'>
                    <strong style='color: #FFD700;'>📌 موضوع:</strong><br><br>
                    <div style='white-space: pre-wrap; color: #E0E0E0; font-size: 1.1em;'>{thread['topic_summary']}</div>
                </div>
                """, unsafe_allow_html=True)
                
                recent_messages = thread.get('recent_messages', [])
                if recent_messages:
                    st.markdown("#### 💬 پیام‌های اخیر:")
                    for msg in recent_messages:
                        author_label = "📤 فرستنده" if msg.get('author_type') == 'sender' else "📥 شما"
                        bg_color = "#1E3A5F" if msg.get('author_type') == 'sender' else "#2E5A3F"
                        st.markdown(f"""
                        <div style='background-color: {bg_color}; color: #FFFFFF; padding: 10px; border-radius: 8px; margin-bottom: 8px;'>
                            <small style='color: #98C1D9;'>{author_label} - {msg.get('created_at', '')}</small><br>
                            {msg.get('message', '')}
                        </div>
                        """, unsafe_allow_html=True)
                
                st.markdown("### 📝 پاسخ شما:")
                
                response_text = st.text_area(
                    "پاسخ خود را بنویسید:",
                    key=f"financial_response_{thread['id']}",
                    height=100,
                    placeholder="مثلاً: باشه، فردا بریز حسابم یا: الان نمیتونم، هفته بعد چطوره؟",
                )
                
                col1, col2 = st.columns(2)
                
                with col1:
                    if st.button(
                        "✅ ارسال پاسخ",
                        key=f"submit_financial_{thread['id']}",
                        type="primary",
                        disabled=not response_text.strip(),
                    ):
                        with st.spinner("در حال ارسال پاسخ..."):
                            submit_response, submit_error = make_api_request(
                                "POST",
                                "/api/v1/feedback/financial-threads/respond",
                                data={
                                    "thread_id": thread['id'],
                                    "response_text": response_text.strip(),
                                },
                            )
                        
                        if submit_error:
                            st.error(submit_error)
                        else:
                            st.success("✅ پاسخ شما ارسال شد!")
                            st.balloons()
                            time.sleep(1)
                            st.rerun()
                
                with col2:
                    if st.button(
                        "🔒 بستن موضوع",
                        key=f"close_financial_{thread['id']}",
                        help="این موضوع را ببند و دیگر پیگیری نکن",
                    ):
                        with st.spinner("در حال ثبت..."):
                            close_response, close_error = make_api_request(
                                "POST",
                                f"/api/v1/feedback/financial-threads/{thread['id']}/close",
                            )
                        
                        if close_error:
                            st.error(close_error)
                        else:
                            st.info("موضوع بسته شد")
                            st.rerun()
                
                st.caption(f"📅 آخرین فعالیت: {thread.get('last_activity_at', 'N/A')}")
    
    if questions:
        st.markdown("---")
        st.subheader("❓ سوالات رابطه")
        
        classes_response, _ = make_api_request("GET", "/api/v1/feedback/relationship-classes")
        relationship_classes = []
        if classes_response:
            relationship_classes = classes_response.get("classes", [])
        
        for idx, question in enumerate(questions):
            with st.expander(
                f"❓ سوال درباره: {question['about_user_id']}",
                expanded=(idx == 0 and not future_requests),
            ):
                st.markdown(f"""
                <div style='background-color: #1E3A5F; color: #FFFFFF; padding: 15px; border-radius: 10px; margin-bottom: 15px; border-left: 4px solid #4CAF50;'>
                    <strong style='color: #FFD700;'>🤔 سوال:</strong><br><br>
                    <div style='white-space: pre-wrap; color: #E0E0E0;'>{question['question_text']}</div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown("### 📝 پاسخ شما:")
                
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    selected_class = None
                    
                    for rel_class in relationship_classes:
                        btn_key = f"btn_{question['id']}_{rel_class['id']}"
                        if st.button(
                            f"{rel_class['emoji']} {rel_class['name']}",
                            key=btn_key,
                            help=rel_class['description'],
                        ):
                            selected_class = rel_class['id']
                            
                            with st.spinner("در حال ثبت پاسخ..."):
                                answer_response, answer_error = make_api_request(
                                    "POST",
                                    "/api/v1/feedback/answer",
                                    data={
                                        "question_id": question['id'],
                                        "relationship_class": selected_class,
                                    },
                                )
                            
                            if answer_error:
                                st.error(answer_error)
                            else:
                                st.success(answer_response.get("message", "✅ ثبت شد!"))
                                st.balloons()
                                st.rerun()
                
                with col2:
                    skip_key = f"skip_{question['id']}"
                    if st.button(
                        "⏭️ رد کردن",
                        key=skip_key,
                        help="این سوال را رد کن و دیگر نپرس",
                    ):
                        with st.spinner("در حال ثبت..."):
                            skip_response, skip_error = make_api_request(
                                "POST",
                                "/api/v1/feedback/skip",
                                data={"question_id": question['id']},
                            )
                        
                        if skip_error:
                            st.error(skip_error)
                        else:
                            st.info(skip_response.get("message", "رد شد"))
                            st.rerun()
                
                st.markdown("---")
                st.caption(f"📅 تاریخ ایجاد: {question.get('created_at', 'N/A')}")
                st.caption(f"📤 تعداد ارسال: {question.get('sent_count', 1)}")
