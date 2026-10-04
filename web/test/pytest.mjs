// node test/pytest.mjs [pytest args]

import { nodeBoot } from '../node-boot.mjs';

// print the Python traceback; Node shows the minified source line
for (const ev of ['unhandledRejection', 'uncaughtException']) process.on(ev, (e) => {
  console.error(String(e?.message ?? e).slice(-4000));
  process.exit(2);
});

const { py } = await nodeBoot();
await py.loadPackage(['pytest', 'pyarrow'], { messageCallback: () => {} });
py.globals.set('ARGS', py.toPy(process.argv.slice(2)));
const code = await py.runPythonAsync(`
import os, sys, pytest
os.chdir('/repo')
pytest.main(['-p', 'no:cacheprovider', 'tests', *ARGS])
`);
process.exit(Number(code));
