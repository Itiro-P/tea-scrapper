# Automação de extração dos 3.141 apps

O pacote adiciona um extrator em lote independente, sem alterar o código anterior.
Usa Python 3.10+ e Ollama local. Não exige pip/venv/npm para executar ou testar.

Leia COMANDOS.md, que contém aplicação, teste, preparação dos 3.141, teste com
três apps, execução completa e retomada. O mesmo guia será instalado em
docs/AUTOMACAO-3141.md no repositório.

Inclui patch, cópia integral dos arquivos adicionados em codigo/, aplicador com
verificação de integridade e VALIDACAO.json.

Foi validado o carregamento/planejamento da coleta real (3.141 apps, 5.122 partes)
e o funcionamento do software com respostas simuladas. Não houve inferência com
modelo real nem acesso ao servidor UTFPR neste ambiente. O primeiro teste no
servidor mede tempo e permite conferir a extração; não é uma avaliação científica
completa da qualidade.

Os resultados dos 100 apps produzidos anteriormente pelo ChatGPT continuam
separados. Não são rotulados como saídas do modelo local.

Não houve commit. Os dados originais de coleta não são alterados.
