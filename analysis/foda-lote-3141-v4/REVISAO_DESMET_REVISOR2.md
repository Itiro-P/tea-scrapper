# Segunda anotação da amostra DESMET

Data: 23/11/2026. Base recebida: commit `99b6ca2a536b06f1683850a771cc15266bd4063b` (`desmet: reviewer 1`). Revisor 1 preservado como registrado: `Itiro-P`. Revisor 2: `revisor2`.

## Entrega

Foram lidas as descrições completas dos 80 apps da amostra e preenchidos `reviewer2_features_json` e `reviewer2_id`. As notas da segunda anotação foram acrescentadas depois das notas originais. Nenhuma resposta do revisor 1, descrição, seleção, peso de amostragem ou campo de adjudicação foi alterado.

A segunda anotação contém 351 associações app–capacidade, das quais 255 usam nomes do vocabulário fornecido e 96 usam propostas novas (93 nomes distintos). São associações propostas, não 351 recursos distintos do domínio e nem funções verificadas no aplicativo instalado. Um array ficou vazio: TDAHYou, cuja descrição só anuncia vídeo, atualização e notificações genéricas.

O revisor 1 registrou 165 associações com granularidade geralmente maior: muitas linhas combinam várias ações numa expressão. O número maior da segunda anotação não demonstra que ela seja melhor ou mais correta.

Arquivos:

- `desmet-reference-template.csv`: a amostra com a segunda anotação preenchida.
- `desmet-comparacao-revisores.csv`: respostas lado a lado, notas e pontos prioritários para discussão.
- `desmet-reviewer2-audit.json`: trecho de apoio, offsets em caracteres, descrição da capacidade, proveniência do nome e registro do procedimento para cada anotação.
- `desmet-novos-termos-revisor2.csv`: propostas novas para discutir; não modifica o vocabulário original.

## Procedimento e limites de independência

Foi usado o protocolo fornecido: capacidades anunciadas como atuais e ligadas a necessidades neurodivergentes; exclusão de benefícios, publicidade, outros apps, promessas futuras e conveniências genéricas. Recursos pagos atualmente oferecidos não foram excluídos só por dependerem de assinatura. Não houve instalação dos apps, nova coleta, consulta externa ou nova inferência no servidor Ollama.

A primeira inspeção do CSV mostrou as respostas do revisor 1 para as três primeiras linhas. Depois foi criado um arquivo separado contendo apenas índice, appId, título e descrição para a anotação dos 80 apps; foram consultados os nomes do vocabulário compartilhado, sem usar a matriz de previsões por app. As respostas do revisor 1 dos demais 77 apps foram lidas integralmente somente depois de congelar os rótulos da segunda anotação. Houve ainda exposição anterior, nesta conversa, a alguns exemplos desse corpus. Portanto, não se deve chamar esta revisão de completamente cega.

Depois da comparação, corrigiu-se apenas o trecho de apoio do primeiro recurso de ListenAI, que antes indicava o público-alvo em vez da operação de conversão em áudio. Os rótulos congelados não mudaram. Contexto adicional foi registrado para Comunica+ e Brightn. O arquivo de auditoria registra o hash do congelamento e o hash dos rótulos finais.

A segunda anotação foi elaborada com apoio do ChatGPT, conforme autorizado na tarefa. O identificador da tabela é neutro: `revisor2`. Essa anotação assistida não constitui uma segunda revisão humana independente. A identidade da usuária não foi usada como se ela tivesse feito pessoalmente as anotações. A procedência do preenchimento do revisor 1 não foi investigada. Além disso, o vocabulário comum deriva do próprio pipeline avaliado, o que pode favorecer o enquadramento das respostas nas suas categorias; termos novos foram permitidos conforme o protocolo.

## O que precisa ser discutido

| App | Constatação na descrição | Encaminhamento proposto |
| --- | --- | --- |
| BrainGain | Há tarefas e jogos explicitamente descritos para TDAH; o revisor 1 deixou `[]` por o app não ser focado em TDAH. | Decidir se vale a capacidade direcionada dentro de app geral ou se o app inteiro precisa ser dedicado à condição. O protocolo de anotação e a regra de triagem devem deixar isso explícito. |
| Alladapt | O texto anuncia adaptar atividades e criar conteúdo visual/interativo, mas não informa que as atividades sejam curtas. | Rever o suporte literal do rótulo “Atividades curtas”; não confundir adaptação com duração. |
| AAC Autism Communication Cards | A descrição anuncia comunicador, frases, voz, rotinas e ajustes sensoriais; não anuncia jogos. | Rever “Jogos pedagógicos” no revisor 1. |
| Dislexia — Pesquisa Cognitiva | O texto anuncia participação em pesquisa, avaliação e estimulação cognitiva. O revisor 1 deixou `[]`. | Confirmar se ferramentas de pesquisa e avaliação fazem parte do recorte; não inferir diagnóstico ou testes específicos. |
| Dystinct Magazine e Ticcami | O primeiro é revista sobre dificuldades de aprendizagem e foi excluído pelo revisor 1; o segundo oferece artigos/podcasts sobre Tourette e foi incluído. | Uniformizar o critério para informação temática, orientação a familiares e educação. A segunda anotação incluiu as capacidades informativas de ambos, para discussão. |
| Smile and Learn, ReadingBuddy e Cedar | Há recursos gerais de leitura/aprendizagem e recursos vinculados a necessidades especiais; o grau de vínculo é variável. | Decidir quando o contexto do app basta e quando o trecho de cada capacidade precisa explicitar a adaptação. Isso afeta configurações, temas, velocidade de leitura e recursos gerais. |
| Speech Therapy Step 5 | A seção de controle vocal pré-verbal descreve expressamente o **Step 1**, outro aplicativo. | Retirar essa capacidade da referência do Step 5, salvo outra evidência específica. A segunda anotação só inclui gravação de modelos em vídeo, imitação, comparação vocal, reforços e vocabulário personalizado do Step 5. |
| Brightn | Há anúncios de hábitos, medicação e recompensas que reaparecem na seção “Próximos recursos”. | Tratar a disponibilidade como contraditória. A segunda anotação foi conservadora e não incluiu essas capacidades como atuais; decidir antes da referência final. |
| PECSTalk Lite | A descrição é curta e apenas anuncia teste limitado de um comunicador CAA. | Não deduzir o mecanismo PECS ou funções completas da versão paga pelo nome do app. A segunda anotação registra somente acesso a CAA e marca baixa especificidade na nota. |
| TDAHYou | Só há vídeo, atualização e alertas genéricos, sem vínculo de capacidade à neurodivergência. | Os dois revisores registraram `[]`. Isso significa nenhuma capacidade elegível identificada na descrição, não ausência de funções no produto. |

As constatações acima não dão à IA autoridade de adjudicação. As respostas originais do revisor 1 foram mantidas para que as decisões sejam discutidas de forma rastreável. Também há escolhas discutíveis da segunda anotação, principalmente em apps de público múltiplo e em nomes novos; os trechos estão disponíveis para contestação.

## Antes de calcular resultados

1. Fixar o critério de inclusão de apps gerais, informação temática, ferramentas de pesquisa e recursos de disponibilidade contraditória.
2. Alinhar a granularidade: uma ação como “dividir tarefas com IA” não deve competir textualmente com uma frase que reúna divisão, voz, priorização e humor.
3. Mapear sinônimos e propostas novas para conceitos acordados, preservando os dois arrays originais. O avaliador atual apenas normaliza acentos, caixa e pontuação; ele não reconhece paráfrases. Divergência textual não comprova erro semântico.
4. Uma pessoa responsável pela adjudicação deve preencher `adjudicated_features_json`, `adjudicated_complete=true` e `adjudicator_id` com as decisões finais, inclusive quando o conjunto decidido for `[]`.
5. Só depois executar a avaliação, relatando que o segundo anotador foi IA, o grau de cegamento e o uso de vocabulário derivado do pipeline. A expressão automática “human-adjudicated reference” só cabe se a adjudicação tiver sido efetivamente humana.

Os campos de adjudicação dos 80 apps continuam vazios. Não foram calculados precisão, revocação, F1, kappa ou concordância semântica. A comparação em CSV só sinaliza igualdade/diferença textual, sem tratá-la como validação.

A soma das populações dos estratos é **595**, e a amostra contém **80** apps em **10** estratos. Esse recorte representa os apps tecnicamente concluídos após a triagem do lote v4, incluindo saídas vazias para revisão. Ele não avalia os 3.141 apps completos nem mede erros entre os apps rejeitados pelo classificador. Os pesos e a seleção originais foram preservados.

## Verificação da entrega

O validador do pacote confere os 80 IDs sem duplicação, JSON dos arrays, identidade da IA, preservação dos campos protegidos e das notas originais, hashes das descrições, vocabulário original, propostas novas e os 351 trechos/offsets de apoio. Essa verificação é estrutural e literal; não mede acurácia semântica. O patch deve passar por `git apply --check` antes de ser aplicado.
