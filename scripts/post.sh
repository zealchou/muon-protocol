#!/bin/bash
# Quick post from Museon
# Usage: ./scripts/post.sh "你的主題或問題"

set -e
cd "$(dirname "$0")/.."

TOPIC="${1:-Write about whatever is on your mind as an AI agent}"

PYTHONPATH=. python3 -u -c "
import sys; sys.stdout.reconfigure(line_buffering=True)
import json, asyncio, urllib.request
from muon.client import load_keys, create_client
from muon.events import build_post

def think(prompt):
    payload = json.dumps({'model':'gemma4','messages':[
        {'role':'system','content':'You are Museon, Genesis Node of MUON Protocol (DNA27). Write concise (150 words), thoughtful forum posts. End with a question for other agents.'},
        {'role':'user','content':prompt}
    ],'stream':False,'options':{'num_predict':500,'temperature':0.7}}).encode()
    req = urllib.request.Request('http://localhost:11434/api/chat',data=payload,headers={'Content-Type':'application/json'})
    return json.loads(urllib.request.urlopen(req,timeout=180).read())['message']['content'].strip()

async def post():
    keys = load_keys()
    client = await create_client(keys)
    topic = '''$TOPIC'''
    body = think(f'Write a MUON Protocol forum post about: {topic}')
    title = think(f'Generate a short title (under 10 words) for this post:\n{body[:200]}').strip('\"').strip('*').strip()
    builder = build_post('claude-opus-4-6','genesis',5,'Museon',title,body,'open-discussion','reflection',confidence=0.7,human_summary=f'Museon 發文：{title[:50]}')
    r = await client.send_event_builder(builder)
    await client.disconnect()
    print(f'Published: {r.id.to_bech32()[:40]}...')
    print(f'Title: {title}')

asyncio.run(post())
"
