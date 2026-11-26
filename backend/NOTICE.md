# Origem e licença

`anomalyguard/torai.py` reimplementa, em funções que devolvem os resultados intermediários, o algoritmo da função `torai` do pacote **RCAEval** (Pham et al.), usado como no artigo do TORAI. O pacote original é distribuído sob a **licença MIT** e é baixado na construção da imagem (Figshare, artigo 31938495, MD5 conferido); partes dele (`preprocess`, `drop_constant`, `_rcd_multimodal`) são **importadas**, não copiadas. A equivalência do ranking com a função original é verificada por um teste automático.
