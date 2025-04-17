DEBUG = False

stimulus_inducer = {
    "name": "us",    # 作为刺激源的agent
    "content": "美国总统特朗普签署行政令，宣布：对所有贸易伙伴加征10%的关税。对与美国贸易逆差最大的国家和地区征收更高的“对等关税”"
}

# 决定终止的超参
MIN_SCORE_THRESHOLD = 50
MAX_ITERATIONS = 5

context = {
    "us": {
        "GDP": 21,
        "失业率": 5.5,
        "通胀率": 3.5
    },
    "china": {
        "GDP": 18,
        "失业率": 5.2,
        "通胀率": 2.1
    },
    "canada": {
        "GDP": 2.1,
        "失业率": 5.5,
        "通胀率": 4.2
    },
    "vietnam": {
        "GDP": 0.4,
        "失业率": 2.3,
        "通胀率": 3.8
    }
}