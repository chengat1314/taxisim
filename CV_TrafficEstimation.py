# -*- coding: utf-8 -*-
"""
Created on Wed Dec 10 18:28:54 2014

@author: brian
"""
from TrafficEstimation import *
from random import shuffle
from multiprocessing import Pool
import csv

# Splits a list into a training set and a test set
# Params:
    # full_data - a list of Trips.  Should already be shuffled
    # fold_id - the fold to be evaluated (should be less than num_folds)
    # num_folds - the total number of folds that are being evaluated
# Returns:
    # train_set - a large slice of the list of Trips
    # test_set - a smaller slice of the list of Trips (mutually exclusive)
def split_train_test(full_data, fold_id, num_folds):
    start_id = int(len(full_data) * float(fold_id) / num_folds)
    end_id = int(len(full_data) * float(fold_id+1) / num_folds)

    
    test = full_data[start_id:end_id]
    train = full_data[:start_id] + full_data[end_id:]
    return train, test
    

# Runs a fold in the cross-validation experiment.  This involves learning the
# link-by-link travel times from the training data, then evaluating on the test data.
# Params: Note that this is passed as a single tuple
    # train - a list of Trips, which will be used as the training set
    # test - a list of Trips, which will be used as the test set
    # nodes_fn - the CSV filename that contains the nodes
    # links_fn - the CSV filename that contains the links
# Returns:
    # iter_avg_errors - a list of average absolute training errors at each iteration
    # iter_perc_errors - a list of average percent trainingerrors at each iteration
    # test_avg_errors - a list of average absolute test errors at each iteration
    # test_avg_errors - a list of average percent test errors at each iteration
    # train - the modified Trip objects from the train set, now with .estimated_time attribute
        # (may be a subset of input due to duplicates, invalids)
    # train - the modified Trip objects from the test set, now with .estimated_time attribute
        # (may be a subset of input due to duplicates, invalids)
def run_fold((train, test, nodes_fn, links_fn)):

    print("Running fold")
    # Load the map and split up the input data
    road_map = Map(nodes_fn, links_fn)
       
    
    # Run the traffic estimation algorithm
    (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors) = estimate_travel_times(
        road_map, train, max_iter=20, test_set=test)
    
    # Remove the trips that were not estimated (duplicates and errors)
    test = [trip for trip in test if trip.dup_times != None]
    train = [trip for trip in train if trip.dup_times != None]    
    
    
    # We have to reset these fields so the objects can be pickled/returned across processes
    # Otherwise we would have to send the whole graph, because of pointers
    for trip_lst in [test, train]:
        for trip in trip_lst:
            trip.origin_node = None
            trip.dest_node = None
            trip.path_links = None
    
    print("Done")
    # Return everything
    return (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test)

# Simple iterator, produces inputs for the run_fold function
def fold_iterator(full_data, nodes_fn, links_fn, num_folds):
    for i in range(num_folds):
        train, test = split_train_test(full_data, fold_id, num_folds) 
        yield (train, test, nodes_fn, links_fn, i, num_folds)


# Takes a list of list, and produces an average list (by averaging the inner lists)
# Lists don't need to be the same size.  Short lists are treated as missing data at the end
# So they only influence slots where they actually have a value
def avg_lists(list_of_lists):
    output_size = max(map(len, list_of_lists))
    sums = [0.0] * output_size
    counts = [0.0] * output_size

    for lst in list_of_lists:
        for i in range(len(lst)):
            sums[i] += lst[i]
            counts[i] += 1
    
    avgs = [sums[i] / counts[i] for i in range(output_size)]
    return avgs

# Combines the outputs from several calls of run_fold().  The errors are averaged across folds
# and raw predictions are concatenated.
def combine_outputs(output_list):
    # Average train/test errors across folds.  This is kind of tedious since they are
    # all lists (error at each iteration)
    train_avg = avg_lists([iter_avg_errors for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list])
    train_perc = avg_lists([iter_perc_errors for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list])
    test_avg = avg_lists([test_avg_errors for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list])
    test_perc = avg_lists([test_perc_errors for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list])
    
    # Concatenate the trips from each training set, test set
    train_set = [trip for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list for trip in train]
    test_set = [trip for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list for trip in test]
    
    return (train_avg, train_perc, test_avg, test_perc, train_set, test_set)

# Outputs a table, which summarizes the predictions on both the training and test sets
# Params:
    # trips - a list of Trips, which have already run through TrafficEstimation
    # filename - the CSV filename to output the results
def output_trips(trips, filename):
    with open(filename, 'w') as f:
        w = csv.writer(f)
        w.writerow(['from_lat','from_lon','to_lat','to_lon','time','est_time','distance','est_distance'])
        for trip in trips:
            line = [trip.fromLat, trip.fromLon, trip.toLat, trip.toLon, trip.time, trip.estimated_time, trip.dist*1609.34, trip.estimated_dist]
            w.writerow(line)

# Performs a cross validation experiment, which splits the full_data into several training/test sets,
# uses the training sets to learn the traffic estimates, predicts on the test sets, reports several
# error metrics, and makes some figures.
# Params:
    # full_data - a list of Trip objects
    # nodes_fn - the CSV filename to read the graph's Nodes from
    # links_fn - the CSV filename to read the graph's Links from
    # num_fold - the K in k-fold cross validation
    # num_cpus - Will run this many folds in parallel
def perform_cv(full_data, nodes_fn, links_fn, num_folds, num_cpus = 1):
    from matplotlib import pyplot as plt
    shuffle(full_data)

    it = fold_iterator(full_data, nodes_fn, links_fn, num_folds)
    pool = Pool(num_cpus)
    output_list = pool.map(run_fold, it)
    (train_avg, train_perc, test_avg, test_perc, train_set, test_set) = combine_outputs(output_list)
    
    
    output_trips(train_set, "train_trips.csv")
    output_trips(test_set, "test_trips.csv")
    
    #Generate figures
    plt.cla()
    plt.plot(train_avg)
    plt.plot(test_avg)
    plt.legend(["Train", "Test"])
    plt.xlabel("Iteration")
    plt.ylabel("Avg Absolute Error (seconds/trip)")
    plt.savefig("avg_error.png")
    
    plt.cla()
    plt.plot(train_perc)
    plt.plot(test_perc)
    plt.legend(["Train", "Test"])
    plt.xlabel("Iteration")
    plt.ylabel("Avg Relative Error")
    plt.savefig("perc_error.png")
    
    plt.cla()
    plt.scatter([trip.time for trip in train_set], [trip.estimated_time for trip in train_set], color="blue")
    plt.scatter([trip.time for trip in test_set], [trip.estimated_time for trip in test_set], color="red")
    plt.xlabel("True Time")
    plt.ylabel("Estimated Time")
    plt.legend(["Train", "Test"])
    plt.savefig("time_scatter.png")
    
    plt.cla()
    plt.plot(sorted([abs(trip.time-trip.estimated_time) for trip in train_set]))
    plt.plot(sorted([abs(trip.time-trip.estimated_time) for trip in test_set]))
    plt.xlabel("Trip Rank")
    plt.ylabel("Absolute Error")
    plt.legend(["Train", "Test"])
    plt.savefig("abs_error_sorted.png")
    
    plt.cla()
    plt.plot(sorted([abs(trip.time-trip.estimated_time)/trip.time for trip in train_set]))
    plt.plot(sorted([abs(trip.time-trip.estimated_time)/trip.time for trip in test_set]))
    plt.legend(["Train", "Test"])
    plt.xlabel("Trip Rank")
    plt.ylabel("Percent Error")
    plt.savefig("perc_error_sorted.png")
    



# An iterator which downsamples the training set, using more data in each iteration
def downsample_iterator(train, test, num_slices, nodes_fn, links_fn):
    for i in range(num_slices):
        cutoff_id = int(float(i+1) * len(train) / num_slices)
        yield (train[:cutoff_id], test, nodes_fn, links_fn)
    



def perform_learning_curve(full_data, nodes_fn, links_fn, num_slices, num_cpus = 1):
    shuffle(full_data)
    
    train, test = split_train_test(full_data, 0, 8)

    
    it = downsample_iterator(train, test, num_cpus, nodes_fn, links_fn)
    pool = Pool(num_cpus)
    output_list = pool.map(run_fold, it)
    
    train_errs = []
    test_errs = []
    for (iter_avg_errors, iter_perc_errors, test_avg_errors, test_perc_errors, train, test) in output_list:
        train_errs.append(iter_avg_errors[-1])
        test_errs.append(test_avg_errors[-1])
    
    
    sizes = [int(float(i+1) * len(train) / num_slices) for i in range(num_slices)]
    
    plt.cla()
    plt.plot(sizes, train_errs)
    plt.plot(sizes, test_errs)
    plt.legend(["Train", "Test"])
    plt.xlabel("Training Set Size")
    plt.ylabel("Avg Absolute Error (seconds/trip)")
    plt.savefig("learning_curve.png")
    
    print("Done!")
    
    



if(__name__=="__main__"):
    print("Loading trips")
    trips = load_trips("sample_2.csv", 200000)
    #print("We have " + str(len(trips)) + " trips")
    
    #print("Loading map")

    
    #perform_cv(trips, "nyc_map4/nodes.csv", "nyc_map4/links.csv", 8, num_cpus=8)
    
    perform_learning_curve(trips, "nyc_map4/nodes.csv", "nyc_map4/links.csv", 24, num_cpus=8)
    print("Done!")
    





    