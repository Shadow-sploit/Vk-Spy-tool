#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import re
import json
import traceback
from datetime import datetime
from pathlib import Path

OUTPUT_DIR = "reports"
MAX_FRIENDS = 100
MAX_SUBSCRIBERS = 100
TIMEOUT = 15

BANNER_COLOR = "bold blue"


try:
    import requests
    from bs4 import BeautifulSoup
    from fake_useragent import UserAgent
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.progress import Progress, SpinnerColumn, TextColumn
    from rich.prompt import Prompt
    from rich.text import Text
    from rich.align import Align
except ImportError as e:
    print(f"[!] pip install requests beautifulsoup4 rich fake-useragent ({e.name})")
    sys.exit(1)

console = Console()

BANNER = r"""
 ██╗   ██╗██╗  ██╗    ███████╗██████╗ ██╗   ██╗
 ██║   ██║██║ ██╔╝    ██╔════╝██╔══██╗╚██╗ ██╔╝
 ██║   ██║█████╔╝     ███████╗██████╔╝ ╚████╔╝  
 ╚██╗ ██╔╝██╔═██╗     ╚════██║██╔═══╝   ╚██╔╝
  ╚████╔╝ ██║  ██╗    ███████║██║        ██║
   ╚═══╝  ╚═╝  ╚═╝    ╚══════╝╚═╝        ╚═╝

   Создал @TeddyCodee 
"""

ua = UserAgent()


def get_headers():
    return {
        "User-Agent": ua.random,
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def parse_target(raw):
    s = raw.strip()
    if not s:
        raise ValueError("Пустой ввод")
    s = re.sub(r"^https?://", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^(www\.)?(m\.)?vk\.com/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^(www\.)?vk\.ru/", "", s, flags=re.IGNORECASE)
    s = s.split("?")[0].split("#")[0].strip("/").lstrip("@")
    s = s.split("/")[0]
    if not s:
        raise ValueError("Не удалось извлечь ID")
    return s


def fetch_page(url):
    try:
        r = requests.get(url, headers=get_headers(), timeout=TIMEOUT)
        if r.status_code == 200:
            return r.text
        console.print(f"[yellow]HTTP {r.status_code}: {url}[/yellow]")
        return None
    except requests.RequestException as e:
        console.print(f"[red]✗ Ошибка запроса: {e}[/red]")
        return None
    except Exception as e:
        console.print(f"[red]✗ {type(e).__name__}: {e}[/red]")
        return None


def safe_text(tag):
    try:
        return tag.get_text(strip=True) if tag else None
    except Exception:
        return None


def parse_profile(html, target):
    profile = {
        "url": f"https://vk.com/{target}",
        "parsed_at": datetime.now().isoformat(),
        "name": None,
        "id": None,
        "status": None,
        "followers_count": None,
        "friends_count": None,
        "photos_count": None,
        "groups_count": None,
        "avatar_url": None,
        "is_private": False,
    }

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return profile

    try:
        name_tag = soup.find("h1", class_=re.compile(r"PageHeader|owner_page_name", re.I))
        if not name_tag:
            name_tag = soup.find("h2", class_=re.compile(r"PageHeader|owner_page_name", re.I))
        if name_tag:
            profile["name"] = safe_text(name_tag)
        else:
            og_title = soup.find("meta", property="og:title")
            if og_title:
                profile["name"] = (og_title.get("content") or "").replace(" | VK", "").strip()
    except Exception:
        pass

    try:
        og_image = soup.find("meta", property="og:image")
        if og_image:
            profile["avatar_url"] = og_image.get("content")
    except Exception:
        pass

    try:
        og_url = soup.find("meta", property="og:url")
        if og_url:
            m = re.search(r"vk\.com/(?:id)?(\d+)", og_url.get("content") or "")
            if m:
                profile["id"] = m.group(1)
    except Exception:
        pass

    if not profile["id"]:
        try:
            id_match = re.search(r'"user_id"\s*:\s*(\d+)', html)
            if id_match:
                profile["id"] = id_match.group(1)
        except Exception:
            pass

    try:
        status_tag = soup.find("div", class_=re.compile(r"ProfileInfo__status|status", re.I))
        if status_tag:
            profile["status"] = safe_text(status_tag)
    except Exception:
        pass

    try:
        counters = soup.find_all("a", class_=re.compile(r"page_counter|ProfileInfo__counter", re.I))
        for c in counters:
            try:
                text = c.get_text(strip=True).lower()
                count_div = c.find("div", class_=re.compile(r"count", re.I))
                if not count_div:
                    continue
                num = int(re.sub(r"[^\d]", "", count_div.get_text()))
                if "друз" in text:
                    profile["friends_count"] = num
                elif "подписчик" in text:
                    profile["followers_count"] = num
                elif "фото" in text:
                    profile["photos_count"] = num
                elif "групп" in text or "сообществ" in text:
                    profile["groups_count"] = num
            except Exception:
                continue
    except Exception:
        pass

    try:
        page_text = soup.get_text().lower()
        if "профиль скрыт" in page_text or "закрытый профиль" in page_text:
            profile["is_private"] = True
    except Exception:
        pass

    return profile


def extract_id_from_href(href):
    m = re.match(r"^id(\d+)$", href)
    return m.group(1) if m else None


def parse_friend_row_old(row):
    try:
        row_id = row.get("id", "")
        uid_match = re.search(r"friends_user_row(\d+)", row_id)
        if not uid_match:
            return None
        uid = uid_match.group(1)
        name_div = row.find("div", class_=re.compile(r"friends_field_title"))
        name = safe_text(name_div)
        link = row.find("a", href=True)
        domain = link["href"].strip("/") if link else None
        img = row.find("img")
        avatar = img.get("src") if img else None
        return {"id": uid, "domain": domain, "name": name, "avatar": avatar}
    except Exception:
        return None


def parse_friends(html):
    friends = []
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        return friends

    try:
        rows = soup.find_all("div", id=re.compile(r"friends_user_row\d+"))
        for row in rows:
            f = parse_friend_row_old(row)
            if f:
                friends.append(f)
    except Exception:
        pass

    if not friends:
        try:
            friend_links = soup.find_all("a", href=re.compile(r"^/[\w\.]+$|^/id\d+$"))
            seen = set()
            skip = {"friends", "photos", "wall", "videos", "audios", "groups",
                    "followers", "subscriptions", "gifts", "notes"}
            for link in friend_links:
                href = (link.get("href") or "").strip("/")
                if not href or href in seen or href in skip:
                    continue
                img = link.find("img")
                name = img.get("alt") if img else safe_text(link)
                if name and len(name) > 1:
                    seen.add(href)
                    friends.append({
                        "id": extract_id_from_href(href),
                        "domain": href,
                        "name": name,
                        "avatar": img.get("src") if img else None,
                    })
        except Exception:
            pass

    return friends[:MAX_FRIENDS]


def parse_followers(html):
    followers = []
    try:
        soup = BeautifulSoup(html, "html.parser")
        blocks = soup.find_all("div", class_=re.compile(r"fans_fan_row|fans_fan_lnk", re.I))
        for block in blocks[:MAX_SUBSCRIBERS]:
            link = block.find("a", href=True)
            if link:
                href = link["href"].strip("/")
                followers.append({
                    "domain": href,
                    "id": extract_id_from_href(href),
                    "name": safe_text(link),
                })
    except Exception:
        pass
    return followers


def save_report(data, out_dir=OUTPUT_DIR):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = (data.get("target") or "unknown").replace("/", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = out_dir / f"vkspy_html_{target}_{ts}"
    json_file = base.with_suffix(".json")
    txt_file = base.with_suffix(".txt")

    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)

    p = data.get("profile") or {}
    lines = [
        "=== VK SPY HTML REPORT ===",
        f"Дата: {data['meta']['timestamp']}",
        f"Цель: {data['target']}",
        f"URL: {p.get('url')}",
        "",
        f"Имя: {p.get('name')}",
        f"ID: {p.get('id')}",
        f"Статус: {p.get('status')}",
        f"Друзей: {p.get('friends_count')}",
        f"Подписчиков: {p.get('followers_count')}",
        f"Фото: {p.get('photos_count')}",
        f"Групп: {p.get('groups_count')}",
        f"Приватный: {p.get('is_private')}",
        "",
        f"Друзей собрано: {len(data.get('friends', []))}",
        f"Подписчиков собрано: {len(data.get('followers', []))}",
    ]
    txt_file.write_text("\n".join(lines), encoding="utf-8")
    return json_file, txt_file


def print_summary(data):
    p = data.get("profile") or {}
    console.print()
    console.rule("[bold cyan]РЕЗУЛЬТАТ[/bold cyan]")
    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_column("Поле", style="bold cyan")
    table.add_column("Значение", style="white")
    table.add_row("Имя", p.get("name") or "-")
    table.add_row("ID", p.get("id") or "-")
    table.add_row("Статус", (p.get("status") or "-")[:70])
    table.add_row("Друзей", str(p.get("friends_count") or "неизвестно"))
    table.add_row("Подписчиков", str(p.get("followers_count") or "неизвестно"))
    table.add_row("Фото", str(p.get("photos_count") or "неизвестно"))
    table.add_row("Приватный профиль", "да" if p.get("is_private") else "нет")
    table.add_row("Друзей спарсено", str(len(data.get("friends", []))))
    table.add_row("Подписчиков спарсено", str(len(data.get("followers", []))))
    console.print(table)


def scan(target):
    data = {
        "meta": {
            "timestamp": datetime.now().isoformat(),
            "tool": "VK Spy HTML Parser v1.3",
        },
        "target": target,
        "profile": None,
        "friends": [],
        "followers": [],
    }

    try:
        with Progress(SpinnerColumn(), TextColumn("[cyan]{task.description}"), console=console) as progress:
            task = progress.add_task("Загрузка профиля...", total=None)

            url = f"https://vk.com/{target}"
            html = fetch_page(url)
            if not html:
                console.print("[red]✗ Не удалось загрузить страницу[/red]")
                return data

            progress.update(task, description="Парсинг профиля...")
            data["profile"] = parse_profile(html, target)

            progress.update(task, description="Загрузка друзей...")
            friends_url = f"https://vk.com/friends?id={target}&section=all"
            friends_html = fetch_page(friends_url)
            if friends_html:
                data["friends"] = parse_friends(friends_html)

            progress.update(task, description="Загрузка подписчиков...")
            followers_url = f"https://vk.com/followers?id={target}"
            followers_html = fetch_page(followers_url)
            if followers_html:
                data["followers"] = parse_followers(followers_html)

            progress.update(task, description="Сохранение...")
            json_file, txt_file = save_report(data)
    except Exception:
        console.print("[red]✗ Критическая ошибка при сканировании:[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        return data

    print_summary(data)
    console.print()
    console.print(Panel(
        f"[green]✓ JSON:[/green] {json_file}\n[green]✓ TXT :[/green] {txt_file}",
        title="[bold]Поиск сохранен сохранены в /reports[/bold]",
        border_style="green",
    ))
    return data


def main():
    console.print(Align.center(Text(BANNER, style=BANNER_COLOR)))
    console.print(Panel(
        "[bold yellow]⚠[/bold yellow]код работает на основе Bs4 поиска по "
        "[bold]открытым[/bold] данными.\n"
        "[dim]Приватные профили и закрытые списки друзей вернут вам пустой результат.[/dim]",
        border_style="yellow",
    ))

    while True:
        raw = Prompt.ask("\n[bold]Введите ссылку на профиль вк или ID[/bold]")
        try:
            target = parse_target(raw)
        except ValueError as e:
            console.print(f"[red]✗ {e}[/red]")
            continue

        console.print(f"[green]✓[/green] Цель: [bold]{target}[/bold]")
        scan(target)

        again = Prompt.ask("\n[bold]Сканировать ещё?[/bold]", choices=["y", "n"], default="n")
        if again.lower() != "y":
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Прервано[/yellow]")
        sys.exit(130)
    except Exception:
        console.print("[red]Fatal Error:[/red]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)