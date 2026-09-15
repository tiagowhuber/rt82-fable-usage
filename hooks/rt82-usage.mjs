// Stop hook: refresh the Fable panel on the RT82 screen.
//
// Fires after every turn, so it must never block the prompt. A push takes a
// couple of seconds and only happens at most every 30 minutes, but even the skip path
// touches the USB bus - so this spawns push.py fully detached and returns
// immediately, the same shape statusline.mjs uses for its usage fetch.
//
// pythonw.exe rather than python.exe: python.exe would flash a console window
// on every turn.

import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { join } from 'node:path';
import { homedir } from 'node:os';

const root = join(homedir(), '.claude', 'rt82');
const py = join(root, 'venv', 'Scripts', 'pythonw.exe');
const script = join(root, 'push.py');

try {
  if (existsSync(py) && existsSync(script)) {
    const child = spawn(py, [script], {
      detached: true,
      stdio: 'ignore',
      windowsHide: true,
      cwd: root,
    });
    child.unref();
  }
} catch {
  // never let a screen update break the session
}

process.exit(0);
