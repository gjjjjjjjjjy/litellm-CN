# Smoke test log

| when | model | endpoint | check | status | s | evidence |
|---|---|---|---|---|---|---|
| 2026-10-23_1409 | qwen3.8-27b | ai.gitee.com | listed | pass |  | listed |
| 2026-10-23_1409 | qwen3.8-27b | ai.gitee.com | basic | pass | 1.9 | content='\n\n42' reasoning_chars=0 usage={'prompt_tokens': 69, 'total_tokens': 121, 'completion_tokens': 52, 'prompt_tokens_details': None} finish=stop |
| 2026-10-23_1409 | qwen3.8-27b | ai.gitee.com | stream | pass | 3.42 | TTFT 0.31s, total 3.42s, 105 tok, 33.8 tok/s; usage_in_stream=yes; answer='\n\n上海是中国东部的直辖市，也是重要的经济、金融和贸易中心。它地处长江入海口，拥有世界级港口和便捷的交通网络。上海既充满' |
| 2026-10-23_1409 | qwen3.8-27b | ai.gitee.com | json_schema | FAIL | 4.1 | response_format accepted but output is not JSON (silent ignore): 城市名：上海   所在国家：中国   人口（百万）：约 24.9（约 2490 万常住人口） |
| 2026-10-23_1409 | qwen3.8-27b | ai.gitee.com | tools | pass | 1.77 | get_weather({'city': '上海'}) |
| 2026-10-23_1409 | qwen3.8-27b | ai.gitee.com | vision | pass | 6.05 | content='\n\n4729' |
| 2026-10-23_1410 | GLM-5.3 | ai.gitee.com | listed | pass |  | listed |
| 2026-10-23_1410 | GLM-5.3 | ai.gitee.com | basic | pass | 2.03 | content='42' reasoning_chars=175 usage={'prompt_tokens': 27, 'total_tokens': 78, 'completion_tokens': 51, 'prompt_tokens_details': None, 'reasoning_tokens': 48} finish=stop |
| 2026-10-23_1410 | GLM-5.3 | ai.gitee.com | stream | pass | 12.15 | TTFT 0.55s, total 12.15s, 402 tok, 34.6 tok/s; usage_in_stream=yes; answer='上海是中国最大的经济中心城市，也是国际金融、贸易和航运中心，坐落于长江入海口。这座城市融合了东西方文化，外滩的万国建筑群' |
| 2026-10-23_1410 | GLM-5.3 | ai.gitee.com | json_schema | FAIL | 6.61 | response_format accepted but output is not JSON (silent ignore): - **城市名**：上海 - **所在国家**：中国 - **人口**：约 2500 万（25 百万）  上海是中国人口最多的城市，也是全球最大的都市区之一。 |
| 2026-10-23_1410 | GLM-5.3 | ai.gitee.com | tools | pass | 1.59 | get_weather({'city': '上海'}) |
| 2026-10-23_1410 | qwen3.8-max | ai.gitee.com | listed | FAIL |  | not in /models |
| 2026-10-23_1410 | qwen3.8-max | ai.gitee.com | basic | FAIL | 0.16 | HTTP 400: {"error":{"code":"400","message":"您绑定的资源包不支持当前模型或算力。建议购买“全资源包”，可支持全部模型。","type":"server_error"}} |
| 2026-10-23_1410 | qwen3.8-max | ai.gitee.com | stream | FAIL |  | HTTP 400: {"error":{"code":"400","message":"您绑定的资源包不支持当前模型或算力。建议购买“全资源包”，可支持全部模型。","type":"server_error"}} |
| 2026-10-23_1410 | qwen3.8-max | ai.gitee.com | json_schema | FAIL | 0.16 | HTTP 400: {"error":{"code":"400","message":"您绑定的资源包不支持当前模型或算力。建议购买“全资源包”，可支持全部模型。","type":"server_error"}} |
| 2026-10-23_1410 | qwen3.8-max | ai.gitee.com | tools | FAIL | 0.15 | HTTP 400: {"error":{"code":"400","message":"您绑定的资源包不支持当前模型或算力。建议购买“全资源包”，可支持全部模型。","type":"server_error"}} |
