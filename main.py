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
    latest_post = soup.find('div', class_='article-index-recipe') 

    # 안전장치: 만약 태그를 찾지 못했다면 에러를 내지 말고 조용히 종료
    if latest_post is None:
        print("웹사이트에서 레시피 요소를 찾지 못했습니다.")
        return None, None
    
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

def get_recipe_details(detail_url):
    """
    레시피 상세 페이지에 접속해서 재료와 만드는 법을 긁어오는 함수입니다.
    """
    response = requests.get(detail_url)
    soup = BeautifulSoup(response.text, 'html.parser')
    
    # 1. 재료(材料) 부분 추출
    ingredients = []
    # 텍스트에 '材料'가 포함된 h3 태그를 찾습니다.
    h3_ingredients = soup.find('h3', string=lambda text: text and '材料' in text)
    
    if h3_ingredients:
        # h3 태그 다음에 오는 형제 태그들을 차례대로 확인합니다.
        for sibling in h3_ingredients.find_next_siblings():
            if sibling.name == 'h3':  # 다음 제목(만드는 법 등)을 만나면 수집을 멈춤
                break
            # 내용이 비어있지 않으면 리스트에 추가 (ul, li 텍스트 모두 커버)
            if sibling.text.strip():
                ingredients.append("- " + sibling.text.strip())
                
    ingredients_jp = "\n".join(ingredients) if ingredients else "재료를 찾을 수 없습니다."
    
    # 2. 만드는 법(作り方) 부분 추출
    instructions = []
    # 텍스트에 '作り方'가 포함된 h3 태그를 찾습니다.
    h3_instructions = soup.find('h3', string=lambda text: text and '作り方' in text)
    
    if h3_instructions:
        for sibling in h3_instructions.find_next_siblings():
            if sibling.name == 'h3':
                break
            if sibling.text.strip():
                instructions.append("- " + sibling.text.strip())
                
    instructions_jp = "\n".join(instructions) if instructions else "만드는 법을 찾을 수 없습니다."
    
    return ingredients_jp, instructions_jp

# --- 메인 실행 흐름 ---
if __name__ == "__main__":
    title_jp, link = get_latest_recipe()
    
    if title_jp and link:
        print(f"레시피 발견: {title_jp}") # 진행 상황 확인용 출력
        
        # 1. 링크로 들어가서 재료와 만드는 법 가져오기
        ingredients_jp, instructions_jp = get_recipe_details(link)
        
        # 2. 번역하기 좋게 하나의 텍스트로 합치기
        full_text_jp = f"제목: {title_jp}\n\n[재료]\n{ingredients_jp}\n\n[만드는 법]\n{instructions_jp}"
        
        # 3. 통째로 AI에게 번역 맡기기
        translated_text = translate_to_korean(full_text_jp)
        
        # 4. 디스코드로 전송하기 (형식 약간 수정)
        data = {
            "content": f"🍵 **새로운 루피시아 레시피가 올라왔어요!**\n🔗 원문 링크: {link}\n\n{translated_text}"
        }
        requests.post(DISCORD_WEBHOOK_URL, json=data)
        print("디스코드 전송 완료!")
    else:
        print("전송할 레시피가 없습니다.")
