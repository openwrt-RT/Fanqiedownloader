import requests
import time
import json
import threading
import argparse
import re
from tqdm import tqdm
from ebooklib import epub
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor

def get_chapter_infos(book_id):
    """获取章节信息（包含item_id和标题）"""
    url = "https://api.cenguigui.cn/api/tomato/api/all_items.php"
    params = {"book_id": book_id}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") != 0:
            raise Exception(f"API错误：{data.get('message')}")
        
        chapters = []
        # 遍历每个卷中的章节
        for volume in data["data"].get("chapterListWithVolume", []):
            for chapter in volume:
                chapters.append({
                    "item_id": chapter["itemId"],
                    "title": chapter["title"].strip()
                })
        return chapters
    
    except Exception as e:
        raise Exception(f"获取章节列表失败：{str(e)}")

def download_chapter(item_id):
    """下载章节内容并获取元数据"""
    url = f"https://api.cenguigui.cn/api/tomato/content.php?item_id={item_id}"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("code") == 200:
            content_data = data.get("data", {})
            return {
                "content": content_data.get("content", ""),
                "author": content_data.get("author", "未知作者"),
                "book_name": content_data.get("book_name", "未知书名"),
                "pic": content_data.get("pic", "")
            }
        else:
            return None
    except Exception as e:
        print(f"下载章节 {item_id} 失败: {str(e)}")
        return None

def sanitize_filename(name):
    """去除文件名中的非法字符"""
    return re.sub(r'[\\/*?:"<>|]', '', name).strip()

def download_and_build_epub(book_id, thread_count=8):
    try:
        print("正在获取章节信息...")
        chapters = get_chapter_infos(book_id)
        total_chapters = len(chapters)
        print(f"共发现 {total_chapters} 个章节")

        if total_chapters == 0:
            raise Exception("没有找到任何章节")

        # 初始化章节内容存储
        chapter_contents = [None] * total_chapters

        # 获取元数据（尝试前3个章节）
        metadata = {"author": "未知作者", "book_name": "未知书名", "pic": ""}
        for i in range(min(3, total_chapters)):
            result = download_chapter(chapters[i]["item_id"])
            if result:
                metadata["author"] = result.get("author", metadata["author"])
                metadata["book_name"] = result.get("book_name", metadata["book_name"])
                metadata["pic"] = result.get("pic", metadata["pic"])
                break

        # 多线程下载所有章节
        print("开始下载章节内容...")
        with tqdm(total=total_chapters, desc="下载进度", unit="章节") as pbar:
            with ThreadPoolExecutor(max_workers=thread_count) as executor:
                futures = []
                for idx in range(total_chapters):
                    future = executor.submit(
                        download_chapter, 
                        chapters[idx]["item_id"]
                    )
                    futures.append((idx, future))

                for idx, future in futures:
                    result = future.result()
                    if result:
                        chapter_contents[idx] = {
                            "title": chapters[idx]["title"],
                            "content": result["content"]
                        }
                    time.sleep(0.1)
                    pbar.update(1)

        # 创建EPUB
        print("正在生成EPUB文件...")
        book = epub.EpubBook()
        
        # 设置元数据
        book.set_title(metadata["book_name"])
        book.add_author(metadata["author"])
        book.set_language('zh')

        # 下载并添加封面
        cover_data = None
        if metadata["pic"]:
            try:
                response = requests.get(metadata["pic"], timeout=10)
                if response.status_code == 200:
                    cover_data = response.content
            except Exception as e:
                print(f"封面下载失败: {str(e)}")

        if cover_data:
            try:
                book.set_cover('cover.jpg', cover_data)
            except Exception as e:
                print(f"封面添加失败: {str(e)}")

        # 创建章节内容
        spine = ['nav']
        chapters_epub = []

        for idx, content_info in enumerate(chapter_contents):
            if not content_info or not content_info["content"]:
                continue

            chapter = epub.EpubHtml(
                title=content_info["title"],
                file_name=f'chapter_{idx}.xhtml',
                lang='zh'
            )
            
            # 处理换行符并使用BeautifulSoup清理内容
            content = content_info["content"].replace("\n", "<br/>")
            soup = BeautifulSoup(
                f"<h1>{content_info['title']}</h1>{content}", 
                'html.parser'
            )
            chapter.content = str(soup).encode('utf-8')
            
            book.add_item(chapter)
            chapters_epub.append(chapter)
            spine.append(chapter)

        # 设置目录和导航
        book.toc = tuple(chapters_epub)
        book.add_item(epub.EpubNcx())
        book.add_item(epub.EpubNav())
        book.spine = spine

        # 生成文件名
        filename = sanitize_filename(metadata["book_name"]) or f"book_{book_id}"
        epub.write_epub(f"{filename}.epub", book, {})
        print(f"EPUB文件已保存为：{filename}.epub")

    except Exception as e:
        print(f"程序出错：{str(e)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="小说下载器")
    parser.add_argument("book_id", type=str, help="小说的 book_id")
    parser.add_argument("-t", "--threads", type=int, default=8, 
                       help="下载线程数（建议不要超过16）")
    args = parser.parse_args()
    
    download_and_build_epub(args.book_id, args.threads)
