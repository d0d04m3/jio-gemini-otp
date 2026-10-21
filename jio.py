import re
import html
import os
import sys
import time
from urllib.parse import unquote
import requests

def load_dotenv(path=None):
    """Lightweight .env loader (no extra dependency)."""
    candidates = []
    if path:
        candidates.append(path)
    try:
        candidates.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
    except Exception:
        pass
    candidates.append(os.path.join(os.getcwd(), ".env"))
    seen = set()
    for p in candidates:
        if not p or p in seen:
            continue
        seen.add(p)
        try:
            if not os.path.isfile(p):
                continue
            with open(p, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and k not in os.environ:
                        os.environ[k] = v
        except Exception:
            continue

load_dotenv()

# =========================================================
# JIO ENDPOINTS
# =========================================================
CHECK_NUMBER_URL = "https://www.jio.com/api/jio-recharge-service/recharge/mobility/number/{mobile}"
SEND_OTP_URL = "https://www.jio.com/api/jio-login-service/login/sendOtp"
VERIFY_OTP_URL = "https://www.jio.com/api/jio-login-service/login/validateOtp"
AUTH_URL = "https://www.jio.com/api/jio-authenticate-service/authenticate/authJsonData"
NAVIGATE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/navigate/Z0241"
ACTIVATE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/activate/Z0241?source=JIO"
GOOGLE_URL = "https://www.jio.com/api/jio-ott-service/ott/subscription/google-ai"
SUBMIT_URL = "https://www.jio.com/api/jio-ott-service/ott/submission/submit"
GOOGLE_PAGE = "https://www.jio.com/selfcare/googleai/?header=no&type=Z0241&source=JIO"

# =========================================================
# SESSION
# =========================================================
def create_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.jio.com",
        "Referer": "https://www.jio.com/selfcare/login/",
    })
    return session

# =========================================================
# HELPERS
# =========================================================
def response_json(response):
    try:
        data = response.json()
    except ValueError:
        return {}
    if isinstance(data, dict):
        return data
    return {}

def api_message(data):
    for key in ("errorMessage", "responseMessage", "responseMsg", "message",):
        if data.get(key):
            return str(data[key])
    return ""

def normalize_mobile(value):
    digits = re.sub(r"\D", "", value)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        return None
    return digits

# =========================================================
# CHECK JIO NUMBER
# =========================================================
def check_jio_number(session, mobile):
    print("\nChecking Jio number...")
    try:
        response = session.get(CHECK_NUMBER_URL.format(mobile=mobile), timeout=20)
    except requests.RequestException as e:
        print("Network error:", e)
        return False
    print("HTTP:", response.status_code)
    data = response_json(response)
    if response.status_code != 200:
        print("Server response:", api_message(data))
        return False
    if data.get("primaryService"):
        print("Jio number detected.")
        return True
    print("Number was not recognized as Jio.")
    if data:
        print("Response message:", api_message(data))
    return False

# =========================================================
# SEND OTP
# =========================================================
def send_otp(session, mobile):
    print("\nSending OTP...")
    payload = {
        "mobileNumber": mobile,
        "loginFlowType": "MOBILE",
        "alternateNumber": "",
    }
    try:
        response = session.post(SEND_OTP_URL, json=payload, timeout=20)
    except requests.RequestException as e:
        print("Network error:", e)
        return False
    print("HTTP:", response.status_code)
    data = response_json(response)
    message = api_message(data)
    if message:
        print("Message:", message)
    if not response.ok:
        return False
    if (data.get("error") or data.get("errorMessage") or str(data.get("status", "")).lower() in {"failed", "failure", "error", "false"}):
        return False
    return True

# =========================================================
# VERIFY OTP
# =========================================================
def verify_otp(session, mobile, otp):
    print("\nVerifying OTP...")
    payload = {
        "mobileNumber": mobile,
        "otp": otp,
    }
    try:
        response = session.post(VERIFY_OTP_URL, json=payload, timeout=20)
    except requests.RequestException as e:
        print("Network error:", e)
        return False
    print("HTTP:", response.status_code)
    data = response_json(response)
    message = api_message(data)
    if message:
        print("Message:", message)
    if not response.ok:
        return False
    if (data.get("error") or data.get("errorMessage") or str(data.get("status", "")).lower() in {"failed", "failure", "error", "false"}):
        return False
    return True

# =========================================================
# GRIZZLY SMS API
# =========================================================
GRIZZLY_BASE_URL = "https://api.grizzlysms.com/stubs/handler_api.php"
DEFAULT_GRIZZLY_SERVICE = "jio"
DEFAULT_GRIZZLY_COUNTRY = "22"

def grizzly_request(api_key, params, timeout=20):
    q = {"api_key": api_key}
    q.update(params)
    try:
        r = requests.get(GRIZZLY_BASE_URL, params=q, timeout=timeout)
    except requests.RequestException as e:
        print("Grizzly network error:", e)
        return ""
    return (r.text or "").strip()

def grizzly_get_balance(api_key):
    text = grizzly_request(api_key, {"action": "getBalance"})
    if text.startswith("ACCESS_BALANCE:"):
        return True, text.split(":", 1)[1].strip()
    return False, text

def grizzly_get_number(api_key, service, country, quiet=False, max_price=None):
    def _log(msg):
        if not quiet:
            print(msg)
    def _params():
        p = {"service": service, "country": country}
        if max_price:
            p["maxPrice"] = str(max_price)
        return p

    for action in ("getNumber", "getNumberV2"):
        if action == "getNumber":
            q = {"action": "getNumber"}
            q.update(_params())
            text = grizzly_request(api_key, q)
            if text.startswith("ACCESS_NUMBER:"):
                parts = text.split(":")
                if len(parts) >= 3:
                    return parts[1].strip(), parts[2].strip()
            if text.strip().startswith("{") and "activationId" in text:
                try:
                    import json as _json
                    obj = _json.loads(text)
                    aid = str(obj.get("activationId", "")).strip()
                    phone = str(obj.get("phoneNumber", "")).strip()
                    if aid and phone:
                        return aid, phone
                except Exception:
                    pass
            if action == "getNumber":
                first_error = text or "(empty response)"
            if text.startswith("ACCESS_NUMBER:"):
                break
            if text in ("BAD_ACTION", "BAD_SERVICE", "NO_NUMBERS") or not text.startswith("ACCESS_"):
                _log(f"Grizzly getNumber failed: {text or '(empty response)'} - trying getNumberV2...")
                continue
            _log("Grizzly getNumber failed:" + (text or "(empty response)"))
            return "", ""
        else:
            q2 = {"action": "getNumberV2"}
            q2.update(_params())
            text = grizzly_request(api_key, q2)
            if not text:
                _log("Grizzly getNumberV2 failed: (empty response)")
                if not quiet:
                    grizzly_diagnose(api_key, service, country)
                return "", ""
            try:
                import json as _json
                if not text.strip().startswith("{"):
                    _log(f"Grizzly getNumberV2 failed: {text}")
                    if not quiet:
                        grizzly_diagnose(api_key, service, country)
                    return "", ""
                obj = _json.loads(text)
                aid = str(obj.get("activationId", "")).strip()
                phone = str(obj.get("phoneNumber", "")).strip()
                if aid and phone:
                    return aid, phone
            except Exception as e:
                _log(f"Grizzly getNumberV2 parse failed: {text[:300]} ({e})")
                if not quiet:
                    grizzly_diagnose(api_key, service, country)
                return "", ""
    return "", ""

def grizzly_wait_for_number(api_key, combos, timeout=1800, interval=15, max_price=None):
    deadline = time.time() + timeout
    attempt = 0
    price_info = f" maxPrice={max_price}" if max_price else " (cheapest tier)"
    print(f"\nWaiting for stock up to {timeout//60}m (trying {', '.join(f'{s}/{c}' for s, c in combos)}{price_info}, every {interval}s)...")
    while True:
        attempt += 1
        for (svc, ctry) in combos:
            aid, phone = grizzly_get_number(api_key, svc, ctry, quiet=True, max_price=max_price)
            if aid and phone:
                mob = normalize_mobile(phone)
                if mob:
                    print(f"\n[{attempt}] Got {svc}/{ctry}: id={aid} ******{mob[-4:]}")
                    return aid, phone, svc, ctry
                try:
                    grizzly_set_status(api_key, aid, 8)
                except Exception:
                    pass
        remaining = int(deadline - time.time())
        if remaining <= 0:
            print(f"\nStock wait timeout after {timeout}s.")
            return "", "", "", ""
        time.sleep(min(interval, max(1, remaining)))

def grizzly_diagnose(api_key, service, country):
    print("\n--- Grizzly diagnose ---")
    print(f"Tried: service={service!r} country={country!r}")

def grizzly_set_status(api_key, activation_id, status):
    return grizzly_request(api_key, {"action": "setStatus", "id": activation_id, "status": str(status)})

def grizzly_get_status(api_key, activation_id):
    return grizzly_request(api_key, {"action": "getStatus", "id": activation_id})

def grizzly_extract_otp(text):
    if not text:
        return ""
    if "STATUS_OK:" in text:
        text = text.split("STATUS_OK:", 1)[1]
    codes6 = re.findall(r"\b\d{6}\b", text)
    if codes6:
        return codes6[0]
    codes = re.findall(r"\b\d{4,8}\b", text)
    if codes:
        return codes[0]
    return ""

def grizzly_poll_otp(api_key, activation_id, timeout=180, interval=5):
    print(f"\nWaiting for Jio OTP on Grizzly (id={activation_id}, timeout={timeout}s)...")
    deadline = time.time() + timeout
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        text = grizzly_get_status(api_key, activation_id)
        if text.startswith("STATUS_OK:"):
            otp = grizzly_extract_otp(text)
            if otp:
                return otp
            raw = text.split(":", 1)[1].strip()
            if raw:
                return raw
        elif text == "STATUS_CANCEL":
            return ""
        otp = grizzly_extract_otp(text)
        if otp:
            return otp
        time.sleep(min(interval, max(1, int(deadline - time.time()))))
    return ""

# =========================================================
# ACTIVATION LINK PARSER
# =========================================================
ACTIVATION_PATTERN = re.compile(r"https?://serviceactivation[.]google[.]com/subscription/new/(?P<token>[A-Za-z0-9_-]{50,})(?P<padding>={0,2})", re.IGNORECASE)

def extract_activation_url(value):
    text = html.unescape(value or "")
    for _ in range(4):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    match = ACTIVATION_PATTERN.search(text)
    if not match:
        return ""
    return "https://serviceactivation.google.com/subscription/new/" + match.group("token") + match.group("padding")

def already_active(value):
    normalized = (" ".join((value or "").lower().replace("_", " ").split()))
    phrases = ("already active", "already activated", "already redeemed", "already claimed", "already availed")
    return any(x in normalized for x in phrases)

def get_activation(session):
    dashboard_headers = {"Accept": "*/*", "Referer": "https://www.jio.com/selfcare/dashboard/"}
    offer_headers = {"Accept": "*/*", "Referer": GOOGLE_PAGE}
    try:
        response = session.get(AUTH_URL, headers=dashboard_headers, timeout=20)
        data = response_json(response)
        if not response.ok or str(data.get("loginFlag", "")).lower() != "true":
            return "session_invalid", ""
        session.get(NAVIGATE_URL, headers=dashboard_headers, timeout=20)
        activate_response = session.get(ACTIVATE_URL, headers=offer_headers, timeout=20)
        activate_data = response_json(activate_response)
        message = api_message(activate_data)
        if already_active(message):
            return "already_active", ""
        google_response = session.get(GOOGLE_URL, headers=offer_headers, timeout=20)
        google_data = response_json(google_response)
        message = api_message(google_data)
        if already_active(message):
            return "already_active", ""
        url = extract_activation_url(str(google_data.get("redirectionURL", "")))
        if not url:
            return "no_activation_url", ""
        try:
            session.get(SUBMIT_URL, headers=offer_headers, timeout=20)
        except requests.RequestException:
            pass
        return "activation_url_found", url
    except requests.RequestException:
        return "activation_api_failed", ""

def verify_and_get_link(session, mobile, otp, grizzly=None):
    if not verify_otp(session, mobile, otp):
        print("\nOTP verification failed.")
        return False
    print("\nOTP verified successfully.")
    status, activation_link = get_activation(session)
    print("\n" + "=" * 65)
    print("RESULT")
    print("=" * 65)
    print("Status:", status)
    if activation_link:
        print("\nActivation link:")
        print(activation_link)
        with open("gemini_activation_link.txt", "w", encoding="utf-8") as f:
            f.write(activation_link + "\n")
        print("\nSaved to gemini_activation_link.txt")
        if grizzly:
            api_key, activation_id = grizzly
            try:
                grizzly_set_status(api_key, activation_id, 6)
            except Exception:
                pass
        return True
    if grizzly:
        api_key, activation_id = grizzly
        try:
            grizzly_set_status(api_key, activation_id, 8)
        except Exception:
            pass
    return False

# =========================================================
# HEADLESS RUN FLOW (GRIZZLY AUTO)
# =========================================================
def run_headless_auto_flow():
    api_key = os.environ.get("GRIZZLY_API_KEY", "").strip()
    if not api_key:
        print("API key is required. Set GRIZZLY_API_KEY environment variable.")
        return

    service = os.environ.get("JIO_SERVICE_CODE", "").strip() or DEFAULT_GRIZZLY_SERVICE
    country = os.environ.get("JIO_COUNTRY_CODE", "").strip() or DEFAULT_GRIZZLY_COUNTRY
    max_price = os.environ.get("JIO_MAX_PRICE", "").strip() or None

    try:
        max_numbers = int(float(os.environ.get("JIO_MAX_NUMBERS", "5").strip()))
    except ValueError:
        max_numbers = 5

    try:
        wait_mins = float(os.environ.get("JIO_WAIT_MINS", "30").strip())
        wait_timeout = int(wait_mins * 60) if wait_mins > 0 else 86400
    except ValueError:
        wait_timeout = 1800

    try:
        wait_interval = max(5, int(float(os.environ.get("JIO_INTERVAL", "15").strip())))
    except ValueError:
        wait_interval = 15

    number_attempt = 0
    first_round = True

    while True:
        number_attempt += 1
        if max_numbers and number_attempt > max_numbers:
            print(f"\nStopped after {max_numbers} numbers.")
            return

        print(f"\n===== Number attempt {number_attempt} =====")
        if first_round:
            activation_id, phone_raw = grizzly_get_number(api_key, service, country, max_price=max_price)
            used_service, used_country = service, country
            first_round = False
        else:
            activation_id, phone_raw = "", ""

        if not activation_id or not phone_raw:
            combos = [(service, country)]
            if service == "jio" and country == "22":
                combos.append(("ot", "22"))
            elif service == "ot" and country == "22":
                combos.append(("jio", "22"))

            activation_id, phone_raw, used_service, used_country = grizzly_wait_for_number(
                api_key, combos, timeout=wait_timeout, interval=wait_interval, max_price=max_price
            )
            if activation_id:
                service, country = used_service, used_country
            else:
                print("\nStill NO_NUMBERS. Aborting.")
                return

        mobile = normalize_mobile(phone_raw)
        if not mobile:
            print(f"Could not normalize phone: {phone_raw}. Cancelling and retrying...")
            try:
                grizzly_set_status(api_key, activation_id, 8)
            except Exception:
                pass
            time.sleep(3)
            continue

        print(f"\nGrizzly activation id: {activation_id}")
        grizzly_set_status(api_key, activation_id, 1)

        session = create_session()
        if not check_jio_number(session, mobile):
            print("\nNot a Jio number. Cancelling and retrying...")
            try:
                grizzly_set_status(api_key, activation_id, 8)
            except Exception:
                pass
            time.sleep(3)
            continue

        if not send_otp(session, mobile):
            print("\nOTP could not be sent. Cancelling and retrying...")
            try:
                grizzly_set_status(api_key, activation_id, 8)
            except Exception:
                pass
            time.sleep(3)
            continue

        print("\nPolling Grizzly for OTP...")
        otp = grizzly_poll_otp(api_key, activation_id, timeout=180, interval=5)
        if not otp:
            print("\nNo OTP received. Cancelling and retrying...")
            try:
                grizzly_set_status(api_key, activation_id, 8)
            except Exception:
                pass
            time.sleep(3)
            continue

        otp_digits = grizzly_extract_otp(otp) or otp.strip()
        success = verify_and_get_link(session, mobile, otp_digits, grizzly=(api_key, activation_id))
        if success:
            print(f"\nDone successfully after {number_attempt} number(s).")
            return

        time.sleep(3)

# =========================================================
# MAIN
# =========================================================
def main():
    print("=" * 65)
    print("Jio Gemini - Headless Automation Mode")
    print("=" * 65)
    run_headless_auto_flow()

if __name__ == "__main__":
    main()
