# AI that remembers everything

This is what I copied from the docs of openui, and following this, I want you to start the agent loop of thinking, implementing, checking, fixing and looping until the task is complete to add this openUI implementation in my chat app.

Remember that this is uv python Pydantic AI + Next JS KumoUI, you have to build on top of this stack and not break the foundation of this project.

Think thoroughly and start the Agent Loop to add OpenUI to my chat application.

When working on UI/UX also read `client/AGENTS.md` and the installed skills.

---

### Requirement

These requirements should be stricly followed in the project

#### Backend

- Get the reference about the project from the README.md in ./backend
- Use falkor DB in here only in the same 6379 port in localhost (I am turning off the previous container)
- The responses are returned in JSON format, and for JSON that is fine, but turn them to TOON format before giving them to the conductor agent.
- Keep the dates as is in the JSON format, but before parsing the dates to TOON convert them to natural format like October 24, 2026 at 1:01:13 PM using something like:

```py
from datetime import datetime

dt = datetime.fromisoformat("2026-10-24T13:01:13.779948+00:00")
local_dt = dt.astimezone()

natural = (
    f"{local_dt.strftime('%B')} {local_dt.day}, {local_dt.year} "
    f"at {local_dt.strftime('%I').lstrip('0')}:{local_dt.strftime('%M:%S %p')} "
    f"{local_dt.tzname()}"
)

print(natural)
```

Flow:
- User enters a prompt to the chat box and submits.
- In the backend, modify and prepend the text with "<USER> said at October 24, 2026 at 1:01:13 PM - <PROMPT>" e.g. "Ayush Singh said at October 24, 2026 at 1:01:13 PM - Hi Joy how are you?" and then give that to the conductor agent.
- This prepended text should be used as the search query in the falkor + qdrant setup with an upper limit of 10
- The final input to the Agent becomes: "<USER> said at October 24, 2026 at 1:01:13 PM - <PROMPT>\n\nExtracted context - <TOON-RESPONSE>" if the response is empty then just pass the prepended text.
- After this, the Agent will respond in natural language, prepend that too with "Joy AI replied at <NATURAL-LANGUAGE-TIME> - <RESPONSE>"
- This combined text (Users prompt with prepended text + Agents response with prepended text - The Toon responses (minus the toon responses)) should be processed for the coref for new chats but for longer chats, use past 3 user prompts and past 3 responses and then coref resolve the user query + current response or think of a better plan testing multiple approaches
- After coref resolution go ahead for relation extraction pipeline (DUL checks) and qdrant chunking and embedding
- Along with all this, the conductor agent should have tools for crud and bulk crud, properly define the tools for the conductor agent for crud and bulk crud and give the agent ids if needed for soft-update/soft-delete
- Obviously you will need to check multiple things and the data for all the users should be completely isolated, one user should never be able to access the data of another user so that the data of users is completely secure (in both falkor and qdrant)
- Create APIs so that any user can delete their data completely from the databases
- Context management should be handled cleanly, the client should not need to share complete chat history with the next prompt, the conversation ID + new prompt should be enough, prepend preprocessing coref extraction everything should be in the backend
- Remeber that I am on free plan of Groq so rate-limiting is an issue
- Use SQLalchemy and also setup postgres and pgadmin with docker compose for storing, conversations
- Optimize for space, ask yourself should we store the same text in qdrant and pg? Why? Why not? And use this approach to solve this memory issue with DOLCE Ultra-lite enforced ontology + Embedding + Re-ranking approach.

#### Frontend

- Add a button in the top right profile dropdown to delete all my data with an alert confirmation modal.
- http://localhost:3000/dashboard should show a Chat UI but without any id in the URL, when the user asks a question only then the id should be shown

Add this to the project docker compose 
```yml
services:
  falkordb:
    image: falkordb/falkordb:latest
    container_name: falkordb
    ports:
      - "6379:6379"
      - "4001:3000"
    environment:
      FALKORDB_PASSWORD: ${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD in .env}
      REDIS_ARGS: "--requirepass ${FALKORDB_PASSWORD:?Set FALKORDB_PASSWORD in .env} --appendonly yes"
      FALKORDB_ARGS: "THREAD_COUNT 8 TIMEOUT_MAX 30000"
    volumes:
      - falkordb_data:/var/lib/falkordb/data
    restart: unless-stopped
    healthcheck:
      test:
        - CMD-SHELL
        - 'redis-cli -a "$${FALKORDB_PASSWORD}" ping 2>/dev/null | grep -q PONG'
      interval: 30s
      timeout: 10s
      retries: 3

volumes:
  falkordb_data:
    driver: local
```

## Toon docs:

uv pip install python-toon

Read more at:
https://pypi.org/project/python-toon/

What I will test?
I will create multiple chats and test if the model remembers things from previous chats, I will tell it multiple things from the chat UI and see if it remembers that.
When I delete a chat it should ask me if I only want to delete the chat or do I also want to delete all the associated data from agents memory (falkor + qdrant) - Do not tell these technical things like falkor or qdrant in the UI just in plain simple ASD-STE100 English
If I change my name from the profile, it should start calling me with that name.
If I open a previous chat and start conversing there, then it should remember the new things.

Think Thoroughly and start the Agent Loop, and finally update the unslopped ASD-STE100 readme in the backend/README.md file for humans.

Yours truly,
Apoorv