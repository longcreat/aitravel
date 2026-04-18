event: message_start
data: {"type":"message_start","message":{"id":"chatcompl_01RrGnRKS15UYzXvKWVemZsE","type":"message","role":"assistant","model":"","parent_uuid":"019d6b24-b37d-7303-92e2-e1304f562432","uuid":"019d6b24-b37d-7977-9627-a0194eadb566","content":[],"stop_reason":null,"stop_sequence":null,"trace_id":"00000000000000009f9606f488f05cd3","request_id":"req_011CZqbbgWBJikemqfTdyw5r"},"discarded_parent_message_uuid":null}
event: content_block_start
data: {"type":"content_block_start","index":0,"content_block":{"start_timestamp":"2026-04-08T03:30:56.402101Z","stop_timestamp":null,"flags":null,"type":"text","text":"","citations":[]}}
event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":" 你"}}
event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"好！让我查一下你所在位置的天气。"}}
event: content_block_stop
data: {"type":"content_block_stop","index":0,"stop_timestamp":"2026-04-08T03:30:56.927918Z"}
event: content_block_start
data: {"type":"content_block_start","index":1,"content_block":{"start_timestamp":"2026-04-08T03:30:57.321995Z","stop_timestamp":null,"flags":null,"type":"tool_use","id":"toolu_017LD11nxhXmedo8kRgcWsaz","name":"weather_fetch","input":{},"message":"Fetching weather","integration_name":null,"integration_icon_url":null,"icon_name":null,"context":null,"display_content":null,"approval_options":null,"approval_key":null,"is_mcp_app":null,"mcp_server_url":null}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"latitude\":"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"30.2"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"741"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":",\"location_name\":"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\"\\u676d\\u5dde"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"\""}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":",\"longitude\":"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"120.1551"}}
event: content_block_delta
data: {"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"}"}}
event: content_block_stop
data: {"type":"content_block_stop","index":1,"stop_timestamp":"2026-04-08T03:30:58.041031Z"}
event: content_block_start
data: {"type":"content_block_start","index":2,"content_block":{"start_timestamp":"2026-04-08T03:30:58.041031Z","stop_timestamp":null,"flags":null,"type":"tool_result","tool_use_id":"toolu_017LD11nxhXmedo8kRgcWsaz","name":"weather_fetch","content":[],"is_error":true,"structured_content":null,"meta":null,"message":null,"integration_name":null,"mcp_server_url":null,"integration_icon_url":null,"icon_name":null,"display_content":null}}
event: content_block_delta
data: {"type":"content_block_delta","index":2,"delta":{"type":"input_json_delta","partial_json":"[{\"type\": \"text\", \"text\": \"Error fetching weather data: Client error '404 Not Found' for url 'https://weather.googleapis.com/v1/forecast/days:lookup?key=AIzaSyCAQci0US4RrrY26XD37kPKmKWqaeLYQ1k&location.latitude=30.2741&location.longitude=120.1551&unitsSystem=IMPERIAL&days=5'\\nFor more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404\", \"uuid\": \"bf5472e6-6f16-411a-967a-7604adc8eeb5\"}]"}}
event: content_block_stop
data: {"type":"content_block_stop","index":2,"stop_timestamp":"2026-04-08T03:30:58.041031Z"}
event: content_block_start
data: {"type":"content_block_start","index":3,"content_block":{"start_timestamp":"2026-04-08T03:31:00.865234Z","stop_timestamp":null,"flags":null,"type":"tool_use","id":"toolu_01QRkNfdjs4DnWZNr18poeQP","name":"weather_fetch","input":{},"message":"Fetching weather","integration_name":null,"integration_icon_url":null,"icon_name":null,"context":null,"display_content":null,"approval_options":null,"approval_key":null,"is_mcp_app":null,"mcp_server_url":null}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"{\"latitude\":"}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"37.3382"}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":",\"location_name\":"}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"\"San Jose, CA"}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"\""}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":",\"longitude\":"}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"-121.8863"}}
event: content_block_delta
data: {"type":"content_block_delta","index":3,"delta":{"type":"input_json_delta","partial_json":"}"}}
event: content_block_stop
data: {"type":"content_block_stop","index":3,"stop_timestamp":"2026-04-08T03:31:01.252054Z"}
event: content_block_start
data: {"type":"content_block_start","index":4,"content_block":{"start_timestamp":"2026-04-08T03:31:01.252054Z","stop_timestamp":null,"flags":null,"type":"tool_result","tool_use_id":"toolu_01QRkNfdjs4DnWZNr18poeQP","name":"weather_fetch","content":[],"is_error":false,"structured_content":null,"meta":null,"message":null,"integration_name":null,"mcp_server_url":null,"integration_icon_url":null,"icon_name":null,"display_content":null}}
event: content_block_delta
data: {"type":"content_block_delta","index":4,"delta":{"type":"input_json_delta","partial_json":"[{\"type\": \"text\", \"text\": \"{\\\"location\\\":\\\"San Jose, CA\\\",\\\"country\\\":\\\"CA\\\",\\\"current\\\":{\\\"temperature\\\":57.4,\\\"condition\\\":\\\"cloudy\\\",\\\"condition_text\\\":\\\"Clear with periodic clouds\\\",\\\"is_day\\\":false},\\\"daily\\\":[{\\\"date\\\":\\\"2026-04-07\\\",\\\"day_of_week\\\":\\\"Tuesday\\\",\\\"high\\\":70.5,\\\"precipitation_chance\\\":5,\\\"precipitation_type\\\":\\\"rain\\\"},{\\\"date\\\":\\\"2026-04-08\\\",\\\"day_of_week\\\":\\\"Wednesday\\\",\\\"high\\\":74.8,\\\"precipitation_chance\\\":0,\\\"precipitation_type\\\":\\\"rain\\\"},{\\\"date\\\":\\\"2026-04-09\\\",\\\"day_of_week\\\":\\\"Thursday\\\",\\\"high\\\":73.3,\\\"precipitation_chance\\\":10,\\\"precipitation_type\\\":\\\"rain\\\"},{\\\"date\\\":\\\"2026-04-10\\\",\\\"day_of_week\\\":\\\"Friday\\\",\\\"high\\\":62.4,\\\"precipitation_chance\\\":75,\\\"precipitation_type\\\":\\\"rain\\\"},{\\\"date\\\":\\\"2026-04-11\\\",\\\"day_of_week\\\":\\\"Saturday\\\",\\\"high\\\":56.9,\\\"precipitation_chance\\\":65,\\\"precipitation_type\\\":\\\"rain\\\"}]}\", \"uuid\": \"f9e4009c-a798-4f3f-8450-5caad2a5002a\"}]"}}
event: content_block_stop
data: {"type":"content_block_stop","index":4,"stop_timestamp":"2026-04-08T03:31:01.252054Z"}
event: content_block_start
data: {"type":"content_block_start","index":5,"content_block":{"start_timestamp":"2026-04-08T03:31:04.331893Z","stop_timestamp":null,"flags":null,"type":"text","text":"","citations":[]}}
event: content_block_delta
data: {"type":"content_block_delta","index":5,"delta":{"type":"text_delta","text":"根"}}
event: content_block_delta
data: {"type":"content_block_delta","index":5,"delta":{"type":"text_delta","text":"据你当前所在的位置（San Jose），今天天"}}
event: content_block_delta
data: {"type":"content_block_delta","index":5,"delta":{"type":"text_delta","text":"气情况如下：\n\n**今日（周三）**\n- "}}
event: content_block_delta
data: {"type":"content_block_delta","index":5,"delta":{"type":"text_delta","text":"🌤️ 多云间晴\n- 最高气温约 **75"}}
event: content_block_delta
data: {"type":"content_block_delta","index":5,"delta":{"type":"text_delta","text":"°F（约 24°C）**\n- 降雨概率极低，几乎为"}}
event: content_block_delta
data: {"type":"content_block_delta","index":5,"delta":{"type":"text_delta","text":" 0%\n\n**近期预报**\n- 周四：73°F，小雨概"}}
data: {"type":"message_stop"}