from config import client, MODEL_NAME

def test_api():
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": "你是一个 helpful assistant。"},
                {"role": "user", "content": "请简单介绍一下你自己。"}
            ],
            stream=False
        )

        print("API 调用成功！")
        print(response.choices[0].message.content)

    except Exception as e:
        print("API 调用失败：")
        print(e)

if __name__ == "__main__":
    test_api()