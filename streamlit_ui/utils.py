
import os
import streamlit as st
import requests
from typing import Any, Tuple
from datetime import datetime


def get_api_url() -> str:
    return os.getenv("API_URL", "http://localhost:8000")


def get_current_timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def check_unread_questions(api_url: str, user_id: str) -> Tuple[bool, int]:
    try:
        response = requests.get(
            f"{api_url}/api/v1/feedback/has-unread/{user_id}",
            timeout=5,
        )
        if response.status_code == 200:
            data = response.json()
            return data.get("has_unread", False), data.get("count", 0)
    except:
        pass
    return False, 0


def make_api_request(
    method: str,
    endpoint: str,
    data: dict[str, Any] | list[dict[str, Any]] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[dict[str, Any] | None, str | None]:
    api_url = st.session_state.get("api_url", get_api_url())
    url = f"{api_url}{endpoint}"

    default_headers = {"Content-Type": "application/json"}
    if headers:
        default_headers.update(headers)

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=default_headers, timeout=30)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, headers=default_headers, timeout=30)
        else:
            return None, f"Method {method} not supported"

        response.raise_for_status()
        return response.json(), None

    except requests.exceptions.ConnectionError:
        return None, "❌ خطا در اتصال به سرور. مطمئن شوید سرور API در حال اجرا است."
    except requests.exceptions.Timeout:
        return None, "❌ خطا: درخواست شما زمان زیادی طول کشید."
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = e.response.json()
            return None, f"❌ خطا HTTP {e.response.status_code}: {error_detail}"
        except:
            return None, f"❌ خطا HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return None, f"❌ خطا غیرمنتظره: {str(e)}"


def make_scheduler_request(
    method: str,
    endpoint: str,
    data: dict[str, Any] | None = None,
    timeout: int = 600,
) -> tuple[dict[str, Any] | None, str | None]:
    api_url = st.session_state.get("api_url", get_api_url())
    url = f"{api_url}{endpoint}"
    headers = {"Content-Type": "application/json"}

    try:
        if method.upper() == "GET":
            response = requests.get(url, headers=headers, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, headers=headers, timeout=timeout)
        else:
            return None, f"Method {method} not supported"

        response.raise_for_status()
        return response.json(), None

    except requests.exceptions.ConnectionError:
        return None, "❌ خطا در اتصال به سرور. مطمئن شوید سرور API در حال اجرا است."
    except requests.exceptions.Timeout:
        return None, f"❌ خطا: درخواست بعد از {timeout} ثانیه timeout شد. پردازش ممکن است هنوز در حال اجرا باشد."
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = e.response.json()
            return None, f"❌ خطا HTTP {e.response.status_code}: {error_detail}"
        except:
            return None, f"❌ خطا HTTP {e.response.status_code}: {e.response.text}"
    except Exception as e:
        return None, f"❌ خطا غیرمنتظره: {str(e)}"


def display_response(response_data: dict[str, Any] | None, error: str | None):
    if error:
        st.error(error)
    elif response_data:
        st.success("✅ درخواست با موفقیت انجام شد!")
        st.json(response_data)
    else:
        st.warning("⚠️ هیچ پاسخ دریافتی وجود ندارد.")
