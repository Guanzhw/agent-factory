# pyright: reportMissingImports=false
"""Optional actual-browser driver for an owned AT10 fixture, no credential output."""
import asyncio
import json
from pathlib import Path
import sys
from urllib.parse import urlparse

def fixture_origin(url):
    parsed = urlparse(url)
    if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or parsed.username or parsed.password:
        raise ValueError('Only the owned loopback fixture is supported')
    return parsed.scheme, parsed.hostname, parsed.port or 80


async def fixture_request(route, origin, headers):
    try:
        matches = fixture_origin(route.request.url) == origin
    except ValueError:
        matches = False
    if not matches:
        await route.abort()
        return
    scoped = {key: value for key, value in route.request.headers.items() if key.lower() != 'authorization'}
    scoped.update(headers)
    # Fetch only this request. Do not forward the injected header through an
    # HTTP redirect; fulfil its response and let the next browser request pass
    # the same exact-origin gate. No context-wide credential header is installed.
    response = await route.fetch(headers=scoped, max_redirects=0)
    await route.fulfill(response=response)


async def main():
    from playwright.async_api import async_playwright
    config=json.loads(Path(sys.argv[1]).read_text())
    origin=fixture_origin(config['baseUrl'])
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch()
        context=await browser.new_context(viewport={'width':1440,'height':1100}, service_workers='block')
        await context.route('**/*', lambda route: fixture_request(route, origin, config['headers']))
        page=await context.new_page()
        errors=[];posts=[]
        page.on('pageerror',lambda error:errors.append(type(error).__name__))
        page.on('request',lambda request:posts.append(request.url) if request.method=='POST' and request.url.endswith('/commands') else None)
        await page.goto(config['baseUrl'])
        await page.locator('.task-row').filter(has_text='Child independent approved work').click(timeout=30000)
        button=page.get_by_role('button',name='恢复本次执行',exact=True)
        await button.wait_for(timeout=30000)
        await page.screenshot(path=config['beforeScreenshot'],full_page=True)
        async with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/commands'),timeout=45000) as pending:
            await button.click()
        response=await pending.value
        if response.status not in {200,201,202}:raise AssertionError('Recovery command was not accepted')
        receipt=await response.json()
        await page.screenshot(path=config['afterScreenshot'],full_page=True)
        if len(posts)!=1 or errors:raise AssertionError({'commandPosts':len(posts),'browserErrors':errors})
        Path(config['receiptPath']).write_text(json.dumps({'receipt':receipt,'commandPosts':len(posts),'browserErrors':errors},indent=2)+'\n')
        await browser.close()


if __name__=='__main__':asyncio.run(main())
