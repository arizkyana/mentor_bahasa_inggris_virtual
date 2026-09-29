import src.app as app


def main():
    app.run()


# hanya akan di eksekusi apabila file main.py (atau file python apapun) dijalankan
# sebagai script cli, contoh:
# uv run main_pooling.py -> variabel __name__ akan berisi "__main__"
if __name__ == "__main__":
    main()
