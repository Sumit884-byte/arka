# Edge-device mode

Arka laptops, Raspberry Pi-class devices, और battery-powered machines के लिए एक सीमित local profile चला सकता है:

```bash
arka edge status
arka edge recommend
```

यह profile compact quantized local models को प्राथमिकता देता है और
`ARKA_MODEL_POLICY=local-only` की सलाह देता है, ताकि prompts hosted services पर fall back न करें।
