# Treatment prompt profile: post-IT-005

The treatment uses the current Core Builder Goal Prompt in `backend/src/demopilot/core_loop.py`.

It requires:

- copy fixture values into a JSON-serializable constant in `card-web/app.js`;
- no `fetch`, XHR, WebSocket, import, service worker or runtime file/network read;
- no HTML inline script, inline event attribute or unsafe HTML injection;
- DOM APIs and `addEventListener` for rendering and events;
- a full authored browser contract rerun after every safety edit;
- preservation of state-machine paths that already passed;
- acceptance child evidence before the candidate can enter the post-publish audit.

Each run must record `prompt_profile=treatment-current`.
