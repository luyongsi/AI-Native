import httpx, asyncio, json

async def main():
    async with httpx.AsyncClient() as http:
        r = await http.post('http://localhost:8000/api/requirements', json={
            'title': '用户个人中心增加手机号绑定功能',
            'description': '用户可绑定/解绑手机号'
        })
        req_id = r.json()['id']
        r2 = await http.post(f'http://localhost:8000/api/requirements/{req_id}/trigger')
        wf = r2.json()
        print(f'REQ_ID={req_id}')
        print(json.dumps(wf, indent=2))

asyncio.run(main())
