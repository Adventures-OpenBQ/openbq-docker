import asyncio,json,threading,tempfile
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from openbb_cboe.utils import helpers
class Handler(BaseHTTPRequestHandler):
    calls=0
    def do_GET(self):
        Handler.calls+=1
        body=json.dumps({'path':self.path}).encode()
        self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def log_message(self,*args):pass
server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
threading.Thread(target=server.serve_forever,daemon=True).start()
with tempfile.TemporaryDirectory() as tmp, patch.object(helpers,'cache_path',return_value=tmp+'/cboe'):
    barrier=threading.Barrier(4)
    def wave(_):
        barrier.wait()
        async def requests():
            return await asyncio.gather(*(helpers.get_cboe_data(f'http://127.0.0.1:{server.server_port}/{n}.json') for n in range(8)))
        return asyncio.run(requests())
    for round in range(3):
        with ThreadPoolExecutor(max_workers=4) as pool:
            results=list(pool.map(wave,range(4)))
        assert results==[[{'path':f'/{n}.json'} for n in range(8)]]*4,results
        if round==0: fetched=Handler.calls
        else: assert Handler.calls==fetched,(Handler.calls,fetched)
server.shutdown()
print('PASS: 96 requests across 12 caller loops, disk hits after first wave')
