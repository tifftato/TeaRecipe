import os
import json
import logging
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # .env 파일에서 환경 변수 로드

# ---------------------------------------------------------
# 로깅 설정
# ---------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. 설정값
# ---------------------------------------------------------
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
LUPICIA_URL = "https://www.lupicia.co.jp/tea/archives/category/recipe"

# 중복 전송 방지를 위해 마지막으로 보낸 레시피 링크를 저장할 파일
LAST_SENT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_sent.json")

# 네트워크 요청 타임아웃 (초)
REQUEST_TIMEOUT = 10

if not OPENAI_API_KEY:
    raise ValueError("OpenAI API 키를 찾을 수 없습니다. .env 파일을 확인해주세요.")

if not DISCORD_WEBHOOK_URL:
    raise ValueError("디스코드 웹훅 URL을 찾을 수 없습니다. .env 파일을 확인해주세요.")

client = OpenAI(api_key=OPENAI_API_KEY)


# ---------------------------------------------------------
# 중복 전송 방지 유틸
# ---------------------------------------------------------
def load_last_sent_link():
    """마지막으로 전송에 성공한 레시피 링크를 파일에서 읽어옵니다."""
    if not os.path.exists(LAST_SENT_FILE):
        return None
    try:
        with open(LAST_SENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("last_link")
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("last_sent.json 읽기 실패, 새로 시작합니다: %s", e)
        return None


def save_last_sent_link(link):
    """전송에 성공한 레시피 링크를 파일에 저장합니다."""
    try:
        with open(LAST_SENT_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_link": link}, f, ensure_ascii=False)
    except OSError as e:
        logger.error("last_sent.json 저장 실패: %s", e)


# ---------------------------------------------------------
# 2. 루피시아 페이지 스크래핑
# ---------------------------------------------------------
def get_latest_recipe():
    """레시피 목록 페이지에서 가장 최신 글의 제목과 링크를 가져옵니다."""
    try:
        response = requests.get(LUPICIA_URL, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("레시피 목록 페이지 요청 실패: %s", e)
        return None, None

    soup = BeautifulSoup(response.text, "html.parser")

    # 예시: 최신 레시피 글의 태그를 찾아 제목과 링크 추출 (실제 HTML 구조에 맞춰 수정 필요)
    latest_post = soup.find("div", class_="article-index-recipe")

    # 안전장치: 만약 태그를 찾지 못했다면 에러를 내지 말고 조용히 종료
    if latest_post is None:
        logger.warning("웹사이트에서 레시피 요소를 찾지 못했습니다. (사이트 구조 변경 가능성)")
        return None, None

    title_tag = latest_post.find("h3")
    link_tag = latest_post.find("a")

    if title_tag is None or link_tag is None or not link_tag.get("href"):
        logger.warning("레시피 제목 또는 링크 태그를 찾지 못했습니다.")
        return None, None

    title_jp = title_tag.text.strip()
    link = link_tag["href"]

    return title_jp, link


def get_recipe_details(detail_url):
    """
    레시피 상세 페이지에 접속해서 재료와 만드는 법을 긁어오는 함수입니다.
    """
    try:
        response = requests.get(detail_url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logger.error("레시피 상세 페이지 요청 실패: %s", e)
        return "재료를 찾을 수 없습니다.", "만드는 법을 찾을 수 없습니다."

    soup = BeautifulSoup(response.text, "html.parser")

    # 1. 재료(材料) 부분 추출
    ingredients = []
    h3_ingredients = soup.find("h3", string=lambda text: text and "材料" in text)

    if h3_ingredients:
        for sibling in h3_ingredients.find_next_siblings():
            if sibling.name == "h3":  # 다음 제목(만드는 법 등)을 만나면 수집을 멈춤
                break
            if sibling.text.strip():
                ingredients.append("- " + sibling.text.strip())

    ingredients_jp = "\n".join(ingredients) if ingredients else "재료를 찾을 수 없습니다."

    # 2. 만드는 법(作り方) 부분 추출
    instructions = []
    h3_instructions = soup.find("h3", string=lambda text: text and "作り方" in text)

    if h3_instructions:
        for sibling in h3_instructions.find_next_siblings():
            if sibling.name == "h3":
                break
            if sibling.text.strip():
                instructions.append("- " + sibling.text.strip())

    instructions_jp = "\n".join(instructions) if instructions else "만드는 법을 찾을 수 없습니다."

    return ingredients_jp, instructions_jp


# ---------------------------------------------------------
# 3. OpenAI API를 이용한 일본어 -> 한국어 번역
# ---------------------------------------------------------
def translate_to_korean(text):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": "너는 차(Tea) 레시피를 전문으로 번역하는 번역가야. 자연스러운 한국어로 번역해줘.",
                },
                {"role": "user", "content": text},
            ],
        )
        return response.choices[0].message.content
    except Exception as e:
        logger.error("번역 요청 실패: %s", e)
        return None


# ---------------------------------------------------------
# 4. 디스코드 웹훅으로 메세지 전송
# ---------------------------------------------------------
def send_to_discord(message):
    """디스코드 웹훅으로 완성된 메시지를 전송합니다. 성공 여부(bool)를 반환합니다."""
    data = {"content": message}
    try:
        response = requests.post(DISCORD_WEBHOOK_URL, json=data, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        logger.error("디스코드 전송 실패: %s", e)
        return False


# ---------------------------------------------------------
# 메인 실행 흐름
# ---------------------------------------------------------
def main():
    title_jp, link = get_latest_recipe()

    if not (title_jp and link):
        logger.info("전송할 레시피가 없습니다.")
        return

    # 중복 전송 방지: 마지막으로 보낸 링크와 같으면 종료
    last_link = load_last_sent_link()
    if link == last_link:
        logger.info("이미 전송한 레시피입니다. (링크: %s) 종료합니다.", link)
        return

    logger.info("새 레시피 발견: %s", title_jp)

    # 1. 링크로 들어가서 재료와 만드는 법 가져오기
    ingredients_jp, instructions_jp = get_recipe_details(link)

    # 2. 번역하기 좋게 하나의 텍스트로 합치기
    full_text_jp = f"제목: {title_jp}\n\n[재료]\n{ingredients_jp}\n\n[만드는 법]\n{instructions_jp}"

    # 3. 통째로 AI에게 번역 맡기기
    translated_text = translate_to_korean(full_text_jp)

    if translated_text is None:
        # 번역 실패 시, 최소한 원문 제목과 링크라도 알림
        logger.warning("번역에 실패하여 원문으로 전송합니다.")
        message = (
            f"🍵 **새로운 루피시아 레시피가 올라왔어요! (번역 실패)**\n"
            f"🔗 원문 링크: {link}\n\n{full_text_jp}"
        )
    else:
        message = (
            f"🍵 **새로운 루피시아 레시피가 올라왔어요!**\n"
            f"🔗 원문 링크: {link}\n\n{translated_text}"
        )

    # 4. 디스코드로 전송하기
    success = send_to_discord(message)

    if success:
        logger.info("디스코드 전송 완료!")
        # 전송에 성공했을 때만 '마지막 링크'를 갱신 (실패 시 다음 실행에서 재시도됨)
        save_last_sent_link(link)
    else:
        logger.error("디스코드 전송에 실패했습니다. 다음 실행에서 재시도됩니다.")


if __name__ == "__main__":
    main()
