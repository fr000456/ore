from jra_turf_2000_upper_model import (
    JRA_COURSES,
    MODEL_FILE_1200 as MODEL_FILE,
    MODEL_GROUP_1200 as MODEL_GROUP,
    TRAINING_FILE_1200 as TRAINING_FILE,
    add_jra_course_features,
    build_jra_turf_1200_upper_training_data,
    canonical_jra_course,
    is_jra_turf_1200_upper,
    load_jra_turf_1200_upper_training_data,
    predict_past_jra_turf_1200_upper,
    train_jra_turf_1200_upper_model,
)


if __name__ == '__main__':
    train_jra_turf_1200_upper_model()
