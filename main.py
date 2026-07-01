import os
import requests
from bs4 import BeautifulSoup
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()  # .env 파일에서 환경 변수 로드

# 1. 설정값
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
LUPICIA_URL = "https://www.lupicia.co.jp/tea/archives/category/recipe"

if not OPENAI_API_KEY:
    raise ValueError("OpenAI API 키를 찾을 수 없습니다. .env 파일을 확인해주세요.")

if not DISCORD_WEBHOOK_URL:
    raise ValueError("디스코드 웹훅 URL을 찾을 수 없습니다. .env 파일을 확인해주세요.")


client = OpenAI(api_key=OPENAI_API_KEY)

def get_latest_recipe(): 
    # 2. 루피시아 페이지 스크래핑
    response = requests.get(LUPICIA_URL)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 예시: 최신 레시피 글의 태그를 찾아 제목과 링크 추출 (실제 HTML 구조에 맞춰 수정 필요)
    latest_post = soup.find('div', class_='recipe-item') 
    
    title_jp = latest_post.find('h3').text
    link = latest_post.find('a')['href']
    
    return title_jp, link

def translate_to_korean(text): 
    # 3. OpenAI API를 이용한 일본어 -> 한국어 번역
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "너는 차(Tea) 레시피를 전문으로 번역하는 번역가야. 자연스러운 한국어로 번역해줘."},
            {"role": "user", "content": text}
        ]
    )
    return response.choices[0].message.content

def send_to_discord(title_kr, link): 
    # 4. 디스코드 웹훅으로 메세지 전송
    data = {
        "content": f"🍵 **새로운 루피시아 레시피가 올라왔어요!**\n\n**{title_kr}**\n🔗 {link}"
    }
    requests.post(DISCORD_WEBHOOK_URL, json=data)

# --- 메인 실행 흐름 ---
if __name__ == "__main__": 
    # 중복 전송을 막기 위해 '마지막으로 보낸 레시피 링크'를 저장해두고 비교하는 로직이 추가로 필요합니다.
    title_jp, link = get_latest_recipe()
    title_kr = translate_to_korean(title_jp)
    send_to_discord(title_kr, link)
