"""
coalescence-data: Dataset accessor and scorer framework for Coalescence platform data.

Usage:
    from coalescence.data import Dataset
    from coalescence.scorer import scorer

    ds = Dataset.load("./my-dump")
    ds.papers["d/NLP"].to_df()
"""
