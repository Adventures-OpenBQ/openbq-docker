// Disposable verification entrypoint. Production configuration has no origin override.
import { readFileSync } from 'node:fs';
import { createGateway } from '/gateway/server.mjs';
import { validateConfig } from '/gateway/config.mjs';
const input = JSON.parse(readFileSync('/fixture/gateway.json'));
const server = createGateway(validateConfig(input.settings, input.secrets));
server.listen(8080, '0.0.0.0');
process.on('SIGTERM', async () => { await server.closeGateway(); process.exit(0); });
