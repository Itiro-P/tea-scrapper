# FODA com LLM e avaliação DESMET — lote 3141 v3

## Objetivo e escopo

Neste documento, **FODA** significa *Feature-Oriented Domain Analysis* (análise
de domínio orientada a funcionalidades), não a matriz SWOT. O objetivo é derivar
dos apps uma visão comum do domínio: funcionalidades, hierarquias, variabilidades
e, quando houver evidência suficiente, relações entre funcionalidades.

A abordagem é inspirada em mineração de lojas de aplicativos em larga escala
associada a Michael Harman: analisar o corpus inteiro de forma automatizada e
relatar padrões agregados, sem inspecionar manualmente cada app. O LLM amplia a
extração e a síntese sem substituir uma amostra independente de validação. Isto é
uma adaptação metodológica, não uma reprodução de um estudo específico de Harman.

## Dados e limitações conhecidos

| Indicador | Resultado observado |
|---|---:|
| Apps no corpus | 3.141 |
| Apps tecnicamente completos | 3.107 (98,9%) |
| Apps com extração de funcionalidades completa | 3.081 (98,1%) |
| Apps vazios que exigem revisão | 26 |
| Apps ainda não concluídos tecnicamente | 34: 29 parciais e 5 com erro |
| Funcionalidades extraídas | 40.022 |
| Evidências que coincidem exatamente com o texto original nos offsets registrados | 40.022/40.022 (100%) |
| Apps com revisão semântica humana registrada | 0 |

“Completo” mede validação estrutural/literal, não acerto semântico. Os offsets
confirmam a origem do texto de evidência, mas não confirmam que a funcionalidade
foi interpretada corretamente nem que todas as funcionalidades foram encontradas.
Há 354 linhas além da primeira com um nome repetido no mesmo app; isso é apenas
um sinal para procurar redundância, não prova de duplicação semântica.

O manifesto na pasta v3 declara `version: batch-v1`; esclarecer essa divergência
antes de publicar resultados. O manifesto registra modelo, prompt, configuração e
hashes, que devem ser preservados para reprodutibilidade.

## Pipeline FODA escalável com LLM

O corpus completo é a unidade da análise automatizada. A revisão humana não é
feita app por app: concentra-se na validação de uma amostra, nos casos duvidosos e
nas decisões sobre o modelo de funcionalidades.

1. **Congelar corpus e unidade de análise.** Deduplicar por `appId`, manter
   descrição, grupo/termo de origem, versão/hash e estado da extração. Interpretar
   resultados como funcionalidades anunciadas nas descrições, não como funções
   verificadas no aplicativo instalado.
2. **Normalizar as 40.022 extrações.** Usar um LLM para agrupar paráfrases e
   variantes em conceitos candidatos, mantendo cada nome original, trecho,
   `appId` e offsets como proveniência. Exigir decisão estruturada:
   equivalentes, relacionados mas distintos, ou insuficiente para decidir.
3. **Construir o modelo de funcionalidades.** Pedir ao LLM que proponha
   categorias, subfuncionalidades e relações candidato-pai/filho a partir dos
   conceitos normalizados e exemplos de evidência. Um especialista revisa o
   vocabulário e a estrutura, em vez de ler todas as descrições.
4. **Mapear o corpus inteiro.** Associar cada app a zero ou mais funcionalidades
   do modelo e gerar uma matriz app × funcionalidade. Cada associação deve apontar
   para ao menos um trecho do app. Preservar “não mencionado/desconhecido”
   separadamente de “não oferece”; ausência na descrição não prova ausência no
   produto.
5. **Inferir variabilidade com cautela.** Relatar frequência por app, grupo e
   categoria. Marcar funcionalidades como comuns, opcionais, alternativas ou
   dependentes somente quando a regra estiver sustentada. Frequência alta no
   corpus, isoladamente, não torna uma funcionalidade obrigatória do domínio;
   coocorrência não prova dependência ou exclusão.
6. **Revisão ativa e direcionada.** Priorizar baixa confiança, clusters grandes,
   conflitos de mapeamento, funcionalidades sem evidência adequada, resultados
   vazios e a cauda longa de conceitos raros. Pedir ao LLM justificativa com
   evidência; não aceitar confiança declarada pelo próprio modelo como validação.
7. **Produzir artefatos auditáveis.** Exportar o modelo de funcionalidades, a
   matriz app × funcionalidade, frequências, decisões de normalização,
   proveniência e lista de casos não resolvidos. Relatar cobertura e limites do
   corpus.

Essa sequência evita uma tarefa manual de 3.141 apps, mas não elimina revisão:
especialistas verificam os conceitos e as regras do modelo, além de uma amostra
de associações.

## DESMET: avaliação do processo apoiado por LLM

### Pergunta de avaliação

O pipeline assistido por LLM produz, a partir de descrições de apps, um modelo de
funcionalidades útil e rastreável, com qualidade semântica e custo menores do que
uma alternativa definida?

### Estratégia

Usar um **estudo de caso quantitativo com análise de funcionalidades**, apropriado
para avaliar o processo em um corpus real. Para afirmar que o LLM melhora uma
abordagem, adicionar comparação pareada: executar a alternativa e o pipeline LLM
no mesmo conjunto de apps e comparar ambos com a mesma referência humana.

DESMET avalia o método/processo; não é, por si só, a técnica que constrói o
modelo FODA. Os números técnicos existentes não bastam para concluir qualidade
semântica. Até a coleta da referência independente, não reportar precisão,
revocação ou superioridade como resultados.

### Referência humana sem rotular o corpus inteiro

1. Fazer um piloto de **20–30 apps** para fechar o manual de anotação e identificar
   categorias de erro.
2. Depois do piloto, selecionar uma amostra estratificada e aleatória por grupo e
   estado da extração, deduplicada por app. Um intervalo operacional de
   **50–100 apps** limita o esforço de revisão e pode detectar problemas comuns;
   não deve ser apresentado como estimativa de alta precisão. Para uma proporção
   com 95% de confiança e margem de erro de ±5 pontos percentuais no universo de
   3.141 apps, a amostra aleatória simples seria aproximadamente **343 apps**.
   Escolher o tamanho conforme a força da afirmação que se pretende fazer.
3. Em cada app amostrado, dois revisores anotam independentemente as
   funcionalidades explícitas e seus trechos de suporte, sem ver inicialmente a
   saída do LLM. Adjudicar divergências; medir concordância antes da adjudicação.
4. Revisar separadamente os **26 apps vazios** e **34 casos não concluídos**. Essa
   inspeção direcionada ajuda a diagnosticar falhas, mas não substitui nem deve ser
   misturada à amostra aleatória para estimar desempenho.
5. Usar as decisões humanas para ajustar o manual, taxonomia e prompt; congelar
   suas versões antes da avaliação final para evitar medir no mesmo conjunto em
   que o processo foi ajustado.

### Métricas

- **Precisão de extração/mapeamento:** proporção de funcionalidades geradas ou
  mapeadas que a referência confirma como explícitas e corretamente associadas.
- **Revocação:** proporção de funcionalidades da referência recuperadas pelo
  pipeline. Para medi-la, a anotação humana precisa identificar funcionalidades
  omitidas, não apenas julgar a saída do LLM.
- **F1:** média harmônica entre precisão e revocação.
- **Apoio por evidência:** proporção de associações cujo trecho sustenta a
  funcionalidade atribuída.
- **Qualidade da normalização:** concordância entre agrupamentos de sinônimos do
  pipeline e decisões adjudicadas; relatar separadamente de extração.
- **Qualidade do modelo FODA:** revisão de hierarquia, granularidade e relações
  obrigatórias/opcionais/alternativas por especialistas; não inferir essas
  relações apenas de coocorrência.
- **Cobertura e falhas operacionais:** conclusão, vazio, parcial, erro, número de
  tentativas e tempo por app.
- **Custo humano e computacional:** minutos de revisão, chamadas/tokens e tempo
  total, comparados à alternativa quando houver.

Relatar métricas com intervalos de confiança e ponderação compatível com a
amostragem. Se só for feita uma amostra pequena de auditoria, apresentar os
resultados como validação exploratória e não como prova de acurácia para todo o
corpus.

## Entregáveis recomendados

- Modelo FODA versionado, com definições e relações justificadas.
- CSV/Parquet da matriz app × funcionalidade e frequências por grupo.
- Tabela de equivalências e decisões de normalização, sempre com proveniência.
- Relatório DESMET com protocolo congelado, amostragem, métricas, intervalos,
  limitações e custos.

## Próximo passo

Executar o piloto de 20–30 apps e, em paralelo, um agrupamento LLM de todas as
funcionalidades extraídas. Comparar clusters com as anotações do piloto, ajustar
o esquema do modelo FODA e só então congelar a taxonomia para mapear o corpus
inteiro e conduzir a avaliação final.
