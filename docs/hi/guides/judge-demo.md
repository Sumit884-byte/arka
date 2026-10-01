# Judge-ready demo packages

एक secret-free evaluation package बनाएँ:

```bash
arka judge-demo init ./judge-demo
arka judge-demo check ./judge-demo
```

इस package में एक manifest, synthetic-data policy, सुरक्षित environment
example, और वे commands शामिल हैं जिन्हें judges किसी मौजूदा Arka installation पर चला सकते हैं।
यह project को rebuild नहीं करता और इसमें production credentials नहीं होते।

समर्थित platforms हैं macOS 12+, glibc वाला Linux, और WSL2 के ज़रिए Windows।
Generated README में हर platform के लिए virtual-environment, activation, और `pip`
installation के निर्देश शामिल होते हैं।
