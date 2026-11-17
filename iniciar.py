"""Ponto de entrada do ScoutBoard: sobe o site na hora, com os dados que já estão em disco.

Uso, a partir da raiz do projeto com o venv ativo:
    python iniciar.py                        # sobe o site
    python iniciar.py --atualizar-tecnicos   # antes, atualiza os técnicos (Wikipédia e Wikidata)
    python iniciar.py --porta 5001

Nada é coletado ao subir: a atualização dos técnicos levava de 2 a 3 minutos a cada início e
agora só roda quando pedida. As fontes externas só são consultadas quando uma página precisa.
"""
import argparse


def atualizar_dados() -> None:
    """Técnicos atuais (Wikipédia e Wikidata)."""
    from coleta import treinadores

    try:
        status = treinadores.coletar()
        print(f"Técnicos atuais pela Wikipédia: {status['atuais_pela_wikipedia']} · "
              f"divergências com o Wikidata: {len(status['conflitos'])}")
    except (OSError, RuntimeError, ValueError, KeyError) as erro:
        print(f"Não foi possível atualizar os técnicos (mantido o arquivo anterior): {erro}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sobe o ScoutBoard.")
    parser.add_argument("--atualizar-tecnicos", action="store_true",
                        help="atualiza os técnicos antes de subir o site (leva alguns minutos)")
    parser.add_argument("--sem-coleta", action="store_true", help="aceito por compatibilidade: já é o padrão")
    parser.add_argument("--porta", type=int, default=5000)
    args = parser.parse_args(argv)

    if args.atualizar_tecnicos and not args.sem_coleta:
        atualizar_dados()

    import sb_web

    app = sb_web.create_app()
    print(f"Site em http://127.0.0.1:{args.porta} (Ctrl+C para parar)")
    # Depuração só com FLASK_DEBUG=1 no .env. Sem o recarregador automático: ele repetiria a atualização
    # a cada alteração.
    app.run(host="127.0.0.1", port=args.porta, debug=app.debug, use_reloader=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
