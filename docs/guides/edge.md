# Edge-device mode

Arka can run a constrained local profile for laptops, Raspberry Pi-class
devices, and battery-powered machines:

```bash
arka edge status
arka edge recommend
```

The profile favors compact quantized local models and recommends
`ARKA_MODEL_POLICY=local-only`, so prompts do not fall back to hosted services.
