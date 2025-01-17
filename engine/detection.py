import os
import csv
import numpy as np
from skimage.feature import peak_local_max
from scipy.ndimage.morphology import grey_dilation
from skimage.measure import label, regionprops_table

from utils.util import save_tif
from engine.metrics import detection_metrics
from engine.base_workflow import Base_Workflow

class Detection(Base_Workflow):
    def __init__(self, cfg, model, post_processing=False):
        super().__init__(cfg, model, post_processing)

        self.cell_count_file = os.path.join(self.cfg.PATHS.RESULT_DIR.PATH, 'cell_counter.csv')
        self.cell_count_lines = []

        self.stats['d_precision'] = 0
        self.stats['d_recall'] = 0
        self.stats['d_f1'] = 0

        self.stats['d_precision_per_crop'] = 0
        self.stats['d_recall_per_crop'] = 0
        self.stats['d_f1_per_crop'] = 0

    def detection_process(self, pred, Y, filenames, metric_names=[]):
        if self.cfg.TEST.DET_LOCAL_MAX_COORDS:
            print("Capturing the local maxima ")
            all_channel_coord = []
            for channel in range(pred.shape[-1]):
                if len(self.cfg.TEST.DET_MIN_TH_TO_BE_PEAK) == 1:
                    min_th_peak = self.cfg.TEST.DET_MIN_TH_TO_BE_PEAK[0]
                else:
                    min_th_peak = self.cfg.TEST.DET_MIN_TH_TO_BE_PEAK[channel]
                if len(self.cfg.TEST.DET_MIN_DISTANCE) == 1:
                    min_distance = self.cfg.TEST.DET_MIN_DISTANCE[0]
                else:
                    min_distance = self.cfg.TEST.DET_MIN_DISTANCE[channel]
                pred_coordinates = peak_local_max(pred[...,channel], threshold_abs=min_th_peak, min_distance=min_distance,
                                                  exclude_border=False)
                all_channel_coord.append(pred_coordinates)

            # Create a file that represent the local maxima
            points_pred = np.zeros((pred.shape[:-1] + (1,)), dtype=np.uint8)
            for n, pred_coordinates in enumerate(all_channel_coord):
                for coord in pred_coordinates:
                        z,y,x = coord
                        points_pred[z,y,x,0] = n+1
                self.cell_count_lines.append([filenames, len(pred_coordinates)])

            if self.cfg.PROBLEM.NDIM == '3D':
                for z_index in range(len(points_pred)):
                    points_pred[z_index] = grey_dilation(points_pred[z_index], size=(3,3,1))
            else:
                points_pred = grey_dilation(points_pred, size=(3,3))

            save_tif(np.expand_dims(points_pred,0), self.cfg.PATHS.RESULT_DIR.DET_LOCAL_MAX_COORDS_CHECK,
                     filenames, verbose=self.cfg.TEST.VERBOSE)
            del points_pred

            all_channel_d_metrics = [0,0,0]
            for ch, pred_coordinates in enumerate(all_channel_coord):
                # Save coords in csv file
                f = os.path.join(self.cfg.PATHS.RESULT_DIR.DET_LOCAL_MAX_COORDS_CHECK, os.path.splitext(filenames[0])[0]+'_class'+str(ch+1)+'.csv')
                with open(f, 'w', newline="") as file:
                    csvwriter = csv.writer(file)
                    csvwriter.writerow(['index', 'axis-0', 'axis-1', 'axis-2'])
                    for nr in range(len(pred_coordinates)):
                        csvwriter.writerow([nr+1] + pred_coordinates[nr].tolist())

                # Calculate detection metrics
                if self.cfg.DATA.TEST.LOAD_GT:
                    exclusion_mask = Y[...,ch] > 0
                    bin_Y = Y[...,ch] * exclusion_mask.astype( float )
                    props = regionprops_table(label( bin_Y ), properties=('area','centroid'))
                    gt_coordinates = []
                    for n in range(len(props['centroid-0'])):
                        gt_coordinates.append([props['centroid-0'][n], props['centroid-1'][n], props['centroid-2'][n]])
                    gt_coordinates = np.array(gt_coordinates)

                    if self.cfg.PROBLEM.NDIM == '3D':
                        v_size = (self.cfg.TEST.DET_VOXEL_SIZE[2], self.cfg.TEST.DET_VOXEL_SIZE[1], self.cfg.TEST.DET_VOXEL_SIZE[0])
                    else:
                        v_size = (1,self.cfg.TEST.DET_VOXEL_SIZE[1], self.cfg.TEST.DET_VOXEL_SIZE[0])
                    print("Detection (class "+str(ch+1)+")")
                    d_metrics = detection_metrics(gt_coordinates, pred_coordinates, tolerance=self.cfg.TEST.DET_TOLERANCE[ch],
                                                  voxel_size=v_size, verbose=self.cfg.TEST.VERBOSE)
                    print("Detection metrics: {}".format(d_metrics))
                    all_channel_d_metrics[0] += d_metrics[1]
                    all_channel_d_metrics[1] += d_metrics[3]
                    all_channel_d_metrics[2] += d_metrics[5]

            if self.cfg.DATA.TEST.LOAD_GT:
                print("All classes "+str(ch+1))
                all_channel_d_metrics[0] = all_channel_d_metrics[0]/Y.shape[-1]
                all_channel_d_metrics[1] = all_channel_d_metrics[1]/Y.shape[-1]
                all_channel_d_metrics[2] = all_channel_d_metrics[2]/Y.shape[-1]
                print("Detection metrics: {}".format(["Precision", all_channel_d_metrics[0],
                                                        "Recall", all_channel_d_metrics[1],
                                                        "F1", all_channel_d_metrics[2]]))

                self.stats[metric_names[0]] += all_channel_d_metrics[0]
                self.stats[metric_names[1]] += all_channel_d_metrics[1]
                self.stats[metric_names[2]] += all_channel_d_metrics[2]

    def normalize_stats(self, image_counter):
        super().normalize_stats(image_counter)

        with open(self.cell_count_file, 'w', newline="") as file:
            csvwriter = csv.writer(file)
            csvwriter.writerow(['filename', 'cells'])
            for nr in range(len(self.cell_count_lines)):
                csvwriter.writerow([nr+1] + self.cell_count_lines[nr])
        if self.cfg.DATA.TEST.LOAD_GT:
            if self.cfg.TEST.STATS.PER_PATCH:
                self.stats['d_precision_per_crop'] = self.stats['d_precision_per_crop'] / image_counter
                self.stats['d_recall_per_crop'] = self.stats['d_recall_per_crop'] / image_counter
                self.stats['d_f1_per_crop'] = self.stats['d_f1_per_crop'] / image_counter
            if self.cfg.TEST.STATS.FULL_IMG:
                self.stats['d_precision'] = self.stats['d_precision'] / image_counter
                self.stats['d_recall'] = self.stats['d_recall'] / image_counter
                self.stats['d_f1'] = self.stats['d_f1'] / image_counter

    def after_merge_patches(self, pred, Y, filenames):
        self.detection_process(pred, Y, filenames, ['d_precision_per_crop', 'd_recall_per_crop', 'd_f1_per_crop'])

    def after_full_image(self, pred, Y, filenames):
        self.detection_process(pred, Y, filenames, ['d_precision', 'd_recall', 'd_f1'])

    def after_all_images(self, Y):
        super().after_all_images(None)

    def print_stats(self, image_counter):
        super().print_stats(image_counter)

        if self.cfg.DATA.TEST.LOAD_GT:
            if self.cfg.TEST.STATS.PER_PATCH:
                print("Detection - Test Precision (merge patches): {}".format(self.stats['d_precision_per_crop']))
                print("Detection - Test Recall (merge patches): {}".format(self.stats['d_recall_per_crop']))
                print("Detection - Test F1 (merge patches): {}".format(self.stats['d_f1_per_crop']))
            if self.cfg.TEST.STATS.FULL_IMG:
                print("Detection - Test Precision (per image): {}".format(self.stats['d_precision']))
                print("Detection - Test Recall (per image): {}".format(self.stats['d_recall']))
                print("Detection - Test F1 (per image): {}".format(self.stats['d_f1']))

        super().print_post_processing_stats()
