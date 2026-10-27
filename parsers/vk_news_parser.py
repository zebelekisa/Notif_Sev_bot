# parsers/vk_news_parser.py
import vk_api


class VKNewsParser:
    """Получает последние посты со стены сообщества СевГУ через VK API."""

    def __init__(self, token: str, group_domain: str = "sevsu"):
        self.vk_session = vk_api.VkApi(token=token)
        self.vk = self.vk_session.get_api()
        self.group_domain = group_domain
        self._last_post_id = None

    def fetch_news(self, count: int = 5) -> list:
        try:
            response = self.vk.wall.get(domain=self.group_domain, count=count)
        except Exception as e:
            print(f"Ошибка VK API: {e}")
            return []

        news = []
        for post in response.get("items", []):
            post_id = post["id"]
            if self._last_post_id is not None and post_id <= self._last_post_id:
                continue

            text = post.get("text", "")[:300]
            link = f"https://vk.com/wall{post['owner_id']}_{post['id']}"
            news.append({
                "id": post_id,
                "title": text.split("\n")[0] if text else "Новость СевГУ",
                "text": text,
                "link": link,
                "date": post.get("date"),
                "source": "СевГУ (VK)",
            })

        if response.get("items"):
            self._last_post_id = response["items"][0]["id"]

        return news
