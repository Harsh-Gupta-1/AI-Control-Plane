import json

with open('C:\\Users\\Harsh Gupta\\.gemini\\antigravity-ide\\brain\\495353be-6bcd-4956-a553-7847bbb276b1\\.system_generated\\logs\\transcript.jsonl', encoding='utf-8') as f:
    for line in f:
        if 'FINAL POST-M10' in line:
            with open('output_prompt.txt', 'w', encoding='utf-8') as out:
                out.write(json.loads(line)['content'])
            break
