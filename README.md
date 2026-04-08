# strait-hormuz-reporter-bot
Tired of the constant news rollercoasters, i built a bot to help me be as close to the action as possible.  
As someone said, *pay attention to what they do, not what they say*.

### modular structure
Tier filtering via config file (YAML) - change what alerts you get, what keywords trigger them, what feeds to watch, all without touching Python.  
   
Railway deployment with a railway.toml + instructions.   
   
Modular design so you can clone this for any topic (Red Sea, Taiwan Strait, oil prices, etc.) by just swapping the config YAML

#### Current tier setup:

🚨 CRITICAL → notify: true
⚠️ HIGH IMPACT → notify: true
📡 UPDATE → notify: false (logged silently, no ping)

#### File structure:
```text
hormuz-alert-bot/
├── main.py           ← the engine, never touch this
├── config.yaml      ← the only file you'll ever edit
├── requirements.txt
├── railway.toml     ← tells Railway how to run it
├── .env.example     ← template (safe to commit)
├── .env             ← your real secrets (gitignored)
└── .gitignore
````


